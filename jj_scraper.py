# Description: Crawl and scrape the visible text from NYS civil service and school webpages

# Version: 3.2




import aiohttp
import asyncio
import glob
import json
import logging
import os
import pickle
import psutil
import re
import shutil
import sys
import subprocess
import timeout_decorator
import traceback
from bs4 import BeautifulSoup
from datetime import datetime, timedelta, date
from playwright.async_api import async_playwright, TimeoutError
from urllib import parse, robotparser
import const




startTime = datetime.now()







# The webpage object
class scrape_c:
    all_done_d = {}  # Each task states if the queue is empty
    prog_count = 0
    total_count = 0

    def __init__(self, org_name, workingurl, current_crawl_level, parent_url, jbw_type, workingurl_dup, req_attempt_num):
        self.org_name = org_name
        self.workingurl = workingurl
        self.current_crawl_level = current_crawl_level
        self.parent_url = parent_url
        self.jbw_type = jbw_type
        self.workingurl_dup = workingurl_dup
        self.req_attempt_num = req_attempt_num
        self.domain = '://'.join(parse.urlparse(workingurl)[:2])  # Includes scheme and www. Used for building abspaths from rel links
        self.dup_domain = workingurl_dup.split('/')[0]  # Used for domain limiter

        # Select jbw list. Used for weighing confidence and finding links
        if self.jbw_type == 'civ':
            self.jbws_high_conf = const.JBWS_CIV_HIGH
            self.jbws_low_conf = const.JBWS_CIV_LOW
        else:
            self.jbws_high_conf = const.JBWS_SU_HIGH
            self.jbws_low_conf = const.JBWS_SU_LOW


    def __str__(self):
        return f'{self.org_name} {self.workingurl} {self.current_crawl_level} {self.parent_url} {self.jbw_type} {self.workingurl_dup} {self.req_attempt_num} {self.domain} {self.dup_domain}'


    # Get important attributes. useful for adding new workingo to queue
    def clean_return(self):
        return self.org_name, self.workingurl, self.current_crawl_level, self.parent_url, self.jbw_type, self.workingurl_dup, self.req_attempt_num


    # Add new working list to the queue
    def add_to_queue(self,
        workingurl = self.workingurl,
        current_crawl_level = self.current_crawl_level,
        parent_url = self.parent_url,
        workingurl_dup = self.workingurl_dup,
        req_attempt_num = 0):

        checked_urls_d_entry(self.workingurl_dup, None)  # Add new entry to CML

        # Create new working list: [org name, URL, crawl level, parent URL, jbw type, url_dup, req attempt]
        new_scrap = scrape_c(self.org_name, workingurl, current_crawl_level, parent_url, self.jbw_type, workingurl_dup, req_attempt_num)
        logger.debug(f'Putting list into queue: {new_scrap}')
        logger.debug(f'From: {self.parent_url}')

        # Put new working list in queue
        try:
            scrape_c.all_urls_q.put_nowait(new_scrap)
            scrape_c.total_count += 1
        except Exception:
            logger.exception(f'__Error trying to put into all_urls_q: {new_scrap}')


    # Get working list from queue
    async def get_scrap(task_id):
        try:
            scrap = scrape_c.all_urls_q.get_nowait()
            scrape_c.all_done_d[task_id] = False
            logger.debug(f'got new working_list {scrap}')
            return scrap

        except asyncio.QueueEmpty:
            logger.info(f'queue empty')
            scrape_c.all_done_d[task_id] = True
            await asyncio.sleep(8)

        except Exception:
            logger.exception(f'QUEUE __ERROR:')
            await asyncio.sleep(8)
            

    # Choose requester based on attempt number
    def choose_requester(self, task_id):
        self.req_attempt_num += 1
        
        if self.req_attempt_num < 3:
            return pw_req(self)

        elif self.req_attempt_num < 5:
            return static_req(self)

        else:
            logger.info(f'All retries exhausted: {self.workingurl} {self.req_attempt_num}')
            scrape_c.prog_count += 1


    # Mark errorlog portal url entry as successful fallback. ie: portal failed so now using homepage instead. don't count as portal error
    def fallback_success(self):
        if self.current_crawl_level < 0:
            try:
                logger.info(f'Homepage fallback success: Overwriting parent_url error: {self.parent_url}')
                scrape_c.error_urls_d[self.parent_url][-1].append('fallback_success')
            except KeyError:
                logger.exception(f'__error parent url key not in scrape_c.error_urls_d {self.parent_url}')
            except Exception:
                logger.exception(f'__error:')


    # Detect redirects and check if the redirected page has already been processed
    def check_red(self):

        # Redirected
        if self.workingurl != self.red_url:
            red_url_dup = dup_checker(self.red_url)

            # Prevent trivial changes (eg: https upgrade) from being viewed as different urls
            if self.workingurl_dup != red_url_dup:
                logger.debug(f'Redirect from/to: {self.workingurl} {self.red_url}')
                self.parent_url = self.workingurl
                self.workingurl = self.red_url
                self.workingurl_dup = red_url_dup

                # Update checked pages conf value to redirected
                conf_val = 'redirected'
                checked_urls_d_entry(self.workingurl_dup, conf_val, self.browser)

                # Skip checked pages using redirected URL
                return proceed(self.red_url)

        # Return True on all other results
        return True



    # If request failed on first URL (portal), use homepage as fallback
    def homepage_fallback(self):
        if self.current_crawl_level != 0:
            return

        logger.info(f'Using URL fallback: {self.parent_url}')

        if proceed(self.parent_url):
            scrape_c.prog_count -= 1  ## undo progress count from final error
            self.add_to_queue(workingurl=self.parent_url, current_crawl_level=-1, parent_url=self.workingurl, workingurl_dup=dup_checker(self.parent_url))



    # Include pagination links
    def get_pagination(self):
        for pag_class in self.soup.find_all(class_='pagination'):
            logger.info(f'pagination class found: {self.workingurl}')
            for anchor_tag in pag_class.find_all('a'):  # Find anchor tags
                logger.info(f'anchor_tag.text {anchor_tag.text}')
                if 'next' in anchor_tag.text.lower():  # Find "next" page url

                    # Add to queue
                    abspath = parse.urljoin(self.domain, anchor_tag.get('href'))
                    if proceed(abspath):
                        logger.info(f'Adding pagination url: {abspath} {self.workingurl}')
                        self.add_to_queue(workingurl=abspath, parent_url=self.workingurl, workingurl_dup=dup_checker(abspath))

                # look for next page button represented by angle bracket
                elif '>' in anchor_tag.text:
                    logger.debug(f'pagination angle bracket {anchor_tag.text}')


    # Find more links
    def get_links(self):
        new_urls = set()
        for anchor_tag in self.soup.find_all('a'):

            # Widen search of jbws if only 1 url in elem. should this be recursive? ie grandparent
            if len(anchor_tag.parent.find_all('a')) == 1:
                tag = anchor_tag.parent
            else:
                tag = anchor_tag

            # Newlines will mess up jbw and bunk detection
            for br in tag.find_all("br"):
                br.replace_with(" ")

            # Skip if the tag contains a bunkword
            if any(bunkword in str(tag).lower() for bunkword in const.BUNKWORDS):
                #logger.debug(f'Bunk word detected: {self.workingurl} {str(tag)[:99]}')
                continue

            # Skip if no jobwords in content
            ## use this for only high conf jbws
            tag_content = str(tag.text).lower()
            if not any(jbw in tag_content for jbw in self.jbws_high_conf):
                #logger.debug(f'No jobwords detected: {workingurl} {tag_content[:99]}')
                continue

            '''
            ## use this for either low or high conf jbws, with new low conf format
            if not any(ttt in tag_content for ttt in jbws_high_conf + jbws_low_conf):
                if self.jbw_type == 'civ': continue
                # Exact match only for sch and uni extra low conf jbws
                else:
                    if not tag_content in jbws_su_x_low: continue
            '''


            bs_url = anchor_tag.get('href')
            abspath = parse.urljoin(self.domain, bs_url).strip()  # Convert relative paths to absolute and strip whitespace
            logger.debug(f'abspath: {abspath} {tag_content}')
            # Remove non printed characters
            #abspath = abspath.encode('ascii', 'ignore').decode()
            #abspath = parse.quote(abspath)

            new_urls.add(abspath)

        logger.info(f'Found {len(new_urls)} new links from {self.workingurl}')
        return new_urls


    # Explore html to find more links and weigh confidence
    def crawler(self):
        try:
            # Search for pagination links before checking crawl level
            get_pagination(self)

            # Limit crawl level
            if self.current_crawl_level > const.MAX_CRAWL_DEPTH:
                return

            logger.debug(f'Begin crawling: {self.workingurl}')
            self.current_crawl_level += 1

            # Check new URLs and append to queue
            for abspath in get_links(self):
                if proceed(abspath):
                    self.add_to_queue(workingurl=abspath, workingurl_dup=dup_checker(abspath), parent_url=self.workingurl)

        except Exception as errex:
            logger.exception(f'\njj_error 1: Crawler error detected. Skipping... {str(traceback.format_exc())} {self}')
            add_errorurls(self, 'jj_error 1', str(errex), True)
            return


    # Determine confidence that a page has job postings
    def count_jbws(self):

        # Count jobwords on the page
        jbw_count = 0
        for i in self.jbws_low_conf:
            if i in self.vis_text: jbw_count += 1
        for i in self.jbws_high_conf:
            if i in self.vis_text: jbw_count += 2

        self.jbw_count = jbw_count


    # Save webpage vis text to file
    def write_results(self):

        # Dont save results if this a fallback homepage
        if self.current_crawl_level < 0:
            return

        # Make dir
        org_path = os.path.join(const.RESULTS_PATH, self.jbw_type, self.org_name)
        if not os.path.exists(org_path):
            os.makedirs(org_path)

        # Make filename
        url_path = parse.quote(self.workingurl, safe=':')  # Replace forward slashes so they aren't read as directory boundaries
        html_path = os.path.join(org_path, url_path)[:254]  # max length is 255 chars

        # Make file content. Separate with ascii delim char
        file_contents_s = f'{self.jbw_count} ▼ {self.browser} ▼ {self.vis_text}'

        # Write text to file
        with open(html_path, "w", encoding='ascii', errors='ignore') as write_html:
            write_html.write(file_contents_s)
        logger.info(f'Success: Write: {url_path}')



# URL requesting super class
class requester_base:
    req_pause = False  # Tell all tasks to wait if there is no internet connectivity

    def __init__(self, scrap):
        self.url = scrap.workingurl


    # Exclude forbidden content types. ex: pdf
    def content_type_check(self, scrap):
        content_type = self.resp.headers['content-type']
        if 'text/html' in content_type:
            return True
        else:
            logger.info(f'jj_error 2{self.ec_char}: Forbidden content type: {content_type} {self.url}')
            add_errorurls(scrap, f'jj_error 2{self.ec_char}', 'Forbidden content type', False)
            return False


    # Check for minimum amount of content. ex soft 404
    def check_vis_text(self, scrap):
        logger.debug(f'begin check_vis_text {self.url}')
        self.vis_text = re.sub(const.WHITE_REG, " ", self.vis_text).lower()  # Reduce excess whitespace with regex

        if len(self.vis_text) > const.EMPTY_CUTOFF:
            return True
        else:
            logger.warning(f'jj_error 7: Empty vis text: {self.url} {len(self.vis_text)}')
            add_errorurls(scrap, 'jj_error 7', 'Empty vis text', False)

            # Debug err7 by saving to separate dir
            url_path = parse.quote(self.url, safe=':')
            html_path = os.path.join(const.ERR7_PATH, url_path)
            with open(html_path[:254], "w", encoding='ascii', errors='ignore') as write_html:
                write_html.write(self.vis_text)

            return False  # Dont retry


    # Copy resp data to scrap
    def add_html(self, scrap):
        scrap.html = self.html
        scrap.vis_text = self.vis_text
        scrap.red_url = str(self.resp.url)  # aiohttp returns yarl obj not str
        scrap.browser = self.name
        scrap.soup = BeautifulSoup(self.html, 'html5lib').find('body')
        logger.debug(f'added html: {self.url}')


    # Act on response status number
    def resp_err_handler(self, scrap):

        # Don't retry req
        if self.resp.status in const.HTTP_RETRY_ERROR_CODES:
            logger.warning(f'jj_error 4{self.ec_char}: {self.url} {self.status_text}')
            add_errorurls(scrap, f'jj_error 4{self.ec_char}', self.status_text, False)

        # Retry req
        else:
            logger.warning(f'jj_error 5{self.ec_char}: request error: {self.url} {self.status_text}')
            add_errorurls(scrap, f'jj_error 5{self.ec_char}', self.status_text, True)


    # Errors not from status code
    def failed_req_handler(self, scrap, errex):
        if isinstance(errex, asyncio.TimeoutError) or isinstance(errex, TimeoutError):
            logger.warning(f'jj_error 3{self.ec_char}: Timeout {self.url}')
            add_errorurls(scrap, f'jj_error 3{self.ec_char}', 'Timeout', True)

        else:
            logger.warning(f'jj_error 6{self.ec_char}: playwright error: {errex} {self.url} {sys.exc_info()[2].tb_lineno}')
            add_errorurls(scrap, f'jj_error 6{self.ec_char}', str(errex), True)



class pw_req(requester_base):
    #session = await async_playwright().start()
    #brow = await session.chromium.launch(args=['--disable-gpu'])

    def __init__(self, scrap):
        self.name = 'pw'
        self.ec_char = 'a'
        super().__init__(scrap)


    async def get_page(self):
        self.context = await pw_req.brow.new_context(ignore_https_errors=True)  ## slow execution here?
        self.page = await self.context.new_page()
        self.page.set_default_navigation_timeout(20000)
        logger.debug(f'using brow: {pw_req.brow._impl_obj._browser_type.name}')


    async def request_url(self):
        logger.info(f'begin req pw {self.url}')
        await self.get_page()
        self.resp = await self.page.goto(self.url)
        await self.page.wait_for_load_state('networkidle')
        self.status_text = f'{self.resp.status} {self.resp.status_text}'
        logger.info(f'end req pw {self.url}')


    async def get_content(self):
        logger.debug(f'begin frame loop: {self.url} {len(self.page.frames)}')

        # Main frame and child frame content
        try:
            self.html, self.vis_text = await asyncio.wait_for(self.get_iframes_content(self.page.main_frame), timeout=3)
            logger.debug(f'end frame loop: {self.url}')

        # Fallback to no child frame content
        except Exception as errex:
            logger.warning(f'child frame error: {errex} {self.url}')
            self.html = await self.page.content()
            self.vis_text = await self.page.inner_text('body')


    # Recursive child frame explorer
    async def get_iframes_content(self, frame):
        try:
            # Discard useless frames
            if frame.name == "about:srcdoc" or frame.name == "about:blank" or not frame.url or frame.url == "about:srcdoc" or frame.url == "about:blank" or frame.is_detached():
                return "", ""

            # Current frame content
            html = await frame.content()
            vis_text = await frame.inner_text('body')

            # Append recursive child frame content
            logger.debug(f'num child frames: {len(frame.child_frames)} {frame}')
            for child_frame in frame.child_frames:
                ret_t = await self.get_iframes_content(child_frame)
                html += ret_t[0]  ## cant do augmented assignment on multiple targets
                vis_text += ret_t[1]
                #logger.debug(f'child frame appended: {frame.url}')

            return f'\n{html}', f'\n{vis_text}'

        except Exception as errex:
            logger.warning(f'get_iframes_content_f __error: {errex}')
            return "", ""


    async def close_page(self):
        try:
            await self.context.close()
        except Exception:
            logger.exception(f'cant close pw context')

            
    async def close_session():
        await pw_req.session.stop()



class pw_ping(pw_req):
    def __init__(self):
        scrap = scrape_c('ping_test', 'http://joesjorbs.com', 0, 'http://joesjorbs.com', 'ping_test', 'joesjorbs.com', 0)
        super().__init__(scrap)



class static_req(requester_base):
    
    def __init__(self, scrap):
        self.name = 'static'
        self.ec_char = 'b'
        super().__init__(scrap)

    async def request_url(self):
        self.resp = await static_req.session.get(self.url, headers={'User-Agent': const.USER_AGENT_S}, ssl=False)
        self.status_text = f'{self.resp.status} {self.resp.reason}'


    async def get_content(self):
        self.html = await self.resp.text()
        self.vis_text = self.get_vis_text()


    def get_vis_text(self):
        vis_soup = BeautifulSoup(self.html, 'html5lib').find('body')
        for x in vis_soup(["script", "style"]):  # Remove script, style, and empty elements
            x.decompose()
        for x in vis_soup.find_all('', {"style" : const.STYLE_REG}):  # Remove all of the hidden style attributes  ## unn?
            x.decompose()
        for x in vis_soup.find_all('', {"type" : 'hidden'}):  # Type="hidden" attribute
            x.decompose()
        for x in vis_soup(class_=const.CLASS_REG):  # Hidden section(s) and dropdown classes
            x.decompose()
        return vis_soup.text


    async def close_page(self):
        if not hasattr(self, 'resp'):
            logger.warning(f'static response does not exist')
        else:
            try:
                self.resp.close()
            except Exception:
                logger.exception(f'cant close static response')


    async def close_session():
        await static_req.session.close()



# Removes extra info from urls to prevent duplicate pages from being checked more than once
def dup_checker(url):
    url_dup = url.split('://')[1].split('#')[0]  # Remove scheme and fragments

    # Remove www subdomains. This works with variants like www3.
    if url_dup.startswith('www'): url_dup = url_dup.split('.', maxsplit=1)[1]

    url_dup = url_dup.replace('//', '/') # Remove double forward slashes outside of scheme
    url_dup = url_dup.strip(' \t\n\r/') # Remove trailing whitespace and slash

    return url_dup.lower()


# Entrypoint into CML
def checked_urls_d_entry(url_dup, *args):
    scrape_c.checked_urls_d[url_dup] = args
    logger.debug(f'Updated outcome for/with: {url_dup} {args}')


# Get domain info and rp
def get_robots_txt(url, url_dup):
    dup_domain = url_dup.split('/')[0]  # Excludes scheme and www
    if dup_domain in bot_excluder.domain_d:  # Use cached robots.txt
        return bot_excluder.domain_d[dup_domain]
    else:
        return bot_excluder(url, url_dup, dup_domain)  # Request robots.txt


# Determine if url should be requested
def proceed(url) -> bool:

    # No scheme
    if not url.startswith('http://') and not url.startswith('https://'):
        logger.warning(f'__Error No scheme at: {url}')
        return False  # Declare not to proceed

    url_dup = dup_checker(url)

    # Exclude checked pages
    if url_dup in scrape_c.checked_urls_d:
        logger.debug(f'Skipping: {url_dup}')
        return False


    # Check robots.txt
    domain_o = get_robots_txt(url, url_dup)
    if not domain_o.can_req(url):
        return False


    # Exclude if the new_url is on the blacklist
    if url_dup in blacklist.combined_l:
        logger.info(f'Blacklist invoked: {url_dup}')
        checked_urls_d_entry(url_dup, 'Blacklist invoked')
        return False

    # Declare to proceed
    return True


# Wait until ping succeeds
async def check_internet_connection():
    while requester_base.req_pause:
        logger.warning(f'req_pause invoked')
        await asyncio.sleep(4)



# Request loop
async def req_looper():
    task_id = asyncio.current_task().get_name()

    # End looper when all tasks report empty queue
    while not all(scrape_c.all_done_d.values()):
        await check_internet_connection()

        # Get url from queue
        scrap = await get_scrap(task_id)
        if not scrap: continue

        requester = scrap.choose_requester(task_id)
        if not requester: continue

        try:
            await requester.request_url()

            if requester.resp.status == 200:
                if not requester.content_type_check(scrap): continue
                await requester.get_content()
                if not requester.check_vis_text(scrap): continue
                requester.add_html(scrap)
                req_success(scrap)
            else:
                requester.resp_err_handler(scrap)

        except asyncio.TimeoutError as errex:  ## not possible without wait for?
            logger.warning(f'looper timeout __error: {errex} {self.workingurl}')
            add_errorurls(self, 'jj_error 8', 'looper timeout', True)

        except Exception as errex:
            requester.failed_req_handler(scrap, errex)
        finally:
            await requester.close_page()

    logger.info(f'Task complete: {task_id}')


# After successful webpage retrieval
def req_success(scrap):
    scrape_c.prog_count += 1

    logger.debug(f'begin robots.txt update {scrap} {bot_excluder.domain_d[scrap.dup_domain]}')
    bot_excluder.domain_d[scrap.dup_domain].update()  # Inc domain_count

    logger.debug(f'begin fallback_success {scrap}')
    scrap.fallback_success()  # Check and update fallback

    scrap.count_jbws()
    checked_urls_d_entry(scrap.workingurl_dup, scrap.jbw_count, scrap.browser)  # Update outcome in scrape_c.checked_urls_d

    logger.debug(f'begin check_red {scrap}')
    if not scrap.check_red():  # Check if redirect URL has been processed already
        return

    scrap.write_results()  # Write result text to file
    scrap.crawler()  # Get more links from page




# url: [[org name, db type, crawl level], [[error number, error desc], [error number, error desc]], [final error flag, fallback flags]]
# Append URLs and info to the errorlog. Allows multiple errors (values) to each URL (key)
def add_errorurls(scrap, err_code, err_desc, back_in_q_b):
    org_name, workingurl, current_crawl_level, parent_url, jbw_type, workingurl_dup, req_attempt_num = scrap.clean_return()

    ## errorlog splits should use non printable char
    # Remove commas from text to prevent splitting errors when reading errorlog
    #err_desc = err_desc.replace(',', '').strip()  ## unn

    # First error for this url
    if not workingurl in scrape_c.error_urls_d:
        scrape_c.error_urls_d[workingurl] = [[org_name, jbw_type, current_crawl_level], [[err_desc, err_code]]]

    # Not the first error for this url
    else:
        try:
            scrape_c.error_urls_d[workingurl][1].append([err_desc, err_code])
        except Exception:
            logger.exception(f'Cant append error to errorlog: {workingurl}')

    # Add URL back to queue
    if back_in_q_b:
        logger.debug(f'Putting back into queue: {workingurl}')
        scrape_c.all_urls_q.put_nowait(scrap)

    # Add final_error flag to errorlog
    else:
        final_error(scrap)

    ## should this be called only on final error or success?
    # Update checked pages value to error code
    checked_urls_d_entry(workingurl_dup, err_code)


# Mark final errors in errorlog
def final_error(scrap):
    try:
        scrape_c.prog_count += 1
        scrape_c.error_urls_d[scrap.workingurl].append(['jj_final_error'])
        homepage_fallback(scrap)
    except Exception:
        logger.exception(f'final_e __error: {scrap.workingurl} {sys.exc_info()[2].tb_lineno}')



async def create_req_sessions():
    pw_req.session = await async_playwright().start()
    pw_req.brow = await pw_req.session.chromium.launch(args=['--disable-gpu'])
    
    timeout = aiohttp.ClientTimeout(total=8)
    static_req.session = await aiohttp.ClientSession(timeout=timeout)


# Check internet connectivity
async def ping_test():
    ping_tally = 0
    while True:
        try:
            logger.debug(f'pw ping begin')
            ping_requester = pw_ping()
            await ping_requester.request_url()
            
            if ping_requester.resp.status == 200:
                requester_base.req_pause = False
                logger.debug(f'pw ping success')
                return
            else:
                raise Exception('pw ping fail')

        except Exception:
            logger.exception(f'__error ping:')
            ping_tally += 1

        finally:
            try:
                await ping_requester.close_page()
            except Exception:
                logger.exception(f'ping: could not close context')

        # Attempt Bash ping on PW failure
        bash_ping_ret = await bash_ping()

        ## should restart pw not nic if bash succeeds but pw fails
        # Restart network interface on any two errors
        if ping_tally > 1 or bash_ping_ret != 0:
            logger.debug(f'check these {ping_tally} {bash_ping_ret}')
            requester_base.req_pause = True
            await restart_nic()


# Bash ping to test internet connection on joesjorbs ip
async def bash_ping():
    logger.info(f'{"Bash ping begin"}')

    proc = await asyncio.create_subprocess_shell(
            "timeout 3 ping -c 1 134.122.12.32",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

    if proc.returncode:
        logger.critical(f'bash ping fail: {proc.returncode}')
    else:
        logger.info(f'bash ping success')

    return proc.returncode


# Restart internet connection
async def restart_nic():
    logger.info(f'{"Restart NIC begin"}')

    # Get NIC UUID
    proc = await asyncio.create_subprocess_shell(
            "nmcli --mode multiline connection show | awk '/UUID/ {print $2;}'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()
    nic_uuid = stdout.decode()
    if proc.returncode:
        logger.critical(f'cant get NIC UUID {proc.returncode}')
        return

    # Deactivate NIC
    proc = await asyncio.create_subprocess_shell(
            "nmcli con down " + nic_uuid,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        logger.critical(f'cant deactivate NIC {proc.returncode} {nic_uuid}')

    # Activate NIC
    proc = await asyncio.create_subprocess_shell(
            "nmcli con up " + nic_uuid,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        logger.critical(f'cant activate NIC {proc.returncode} {nic_uuid}')
    else:
        logger.info(f'NIC start success')


# Write shared objects to file to save progress
async def save_progress():
    logger.debug(f'begin prog save')
    try:
        # Pickle queue of scraps
        with open(const.QUEUE_PATH, "wb") as f:
            pickle.dump(scrape_c.all_urls_q, f)

        # CML, errorlog, and multiorg
        for each_path, each_dict in (const.CHECKED_PATH, scrape_c.checked_urls_d), (const.ERROR_PATH, scrape_c.error_urls_d), (const.MULTI_ORG_D_PATH, scrape_c.multi_org_d):
            with open(each_path, "w") as f:
                json.dump(each_dict, f)
                
        logger.debug(f'prog save success')
        
    except Exception:
        logger.exception(f'\n prog_f __ERROR: {sys.exc_info()[2].tb_lineno}')


async def check_mem():
    mem_use = psutil.virtual_memory()[2]
    logger.info(f'Memory usage: {mem_use}')
    if mem_use > 70:
        logger.error(f'\n Memory usage too high \n')


# Display progress
def display_prog():
    logger.info(f'\nProgress: {scrape_c.prog_count} of {scrape_c.total_count}')
    for context in pw_req.brow.contexts:
        logger.info(f'{pw_req.brow._impl_obj._browser_type.name} open pages: {len(context.pages)} {context.pages}')
    logger.info(f'running tasks: {len(asyncio.all_tasks())}')
    #prant('running tasks:', asyncio.all_tasks())


# Start async tasks
async def run_scraper():
    for i in range(const.SEMAPHORE):
        task = asyncio.create_task(req_looper())
        scrape_c.all_done_d[task.get_name()] = False


# Run housekeeping funcs and display progress
async def maintenance():
    try:
        for intermittent_f in save_progress, ping_test, check_mem:
            await intermittent_f()  # save_progress and check_mem need to be async because ping_test is
            display_prog()
            await asyncio.sleep(8)

    except Exception:
        logger.exception(f'\nmaintenance __ERROR: {sys.exc_info()[2].tb_lineno}')
        await asyncio.sleep(2)


# Main event loop
async def main():
    logger.info(f'\n Program Start')
    await create_req_sessions()
    await run_scraper()

    # Wait for scraping to finish
    while not all(scrape_c.all_done_d.values()):
        await maintenance()

    # Scrape complete
    logger.info(f'  Scrape complete  '.center(70, '='))
    await cleanup()


# Close browser sessions
async def cleanup():
    try:
        await pw_req.brow.close()
    except Exception:
        logger.exception(f'\ncant close pw brow')

    for req_class in requester_base.__subclasses__():
        try:
            await req_class.close_session()
        except Exception:
            logger.exception(f'\ncant close session: {req_class.__name__}')



# robots.txt and domain tracker used for rate limiting
# robots.txts are requested before any url from that domain enter the queue
class bot_excluder:
    import ssl
    ssl._create_default_https_context = ssl._create_unverified_context  # rp.read req can throw error
    domain_d = {}  # Holds all robots.txts

    @timeout_decorator.timeout(8)
    def __init__(self, url, url_dup, dup_domain):
        logger.info(f'new domain: {dup_domain}')
        self.rp = robotparser.RobotFileParser()
        self.last_req_ts = 0.0
        self.domain_count = 0

        # Get robots.txt
        self.set_robots_txt_path(url)
        try:
            self.rp.read()  # req
            logger.debug(f"rp printout: {self.rp.allow_all} {self.rp.disallow_all} {self.rp.can_fetch('*', '*')} {self.rp.url}")
        except Exception as errex :
            logger.warning(f'__error: rp read: {dup_domain} {errex}')
            self.rp = None

        # Store rp so it is requested only once
        bot_excluder.domain_d[dup_domain] = self


    def set_robots_txt_path(self, url):
        domain = '://'.join(parse.urlparse(url)[:2])  # Includes scheme and www.
        self.rp.set_url(parse.urljoin(domain, "robots.txt"))


    # After req
    def update(self):
        #logger.debug(f"rp update start")
        self.last_req_ts = datetime.now().timestamp()
        self.domain_count += 1
        #logger.debug(f"rp update complete")


    def can_req(self, url):
        if self.rp and len(self.rp.__str__()) > 1:
            if not self.rp.can_fetch('*', url):
                logger.info(f'rp can not fetch: {url}')
                return False

            # Domain rate limiter
            crawl_delay = self.rp.crawl_delay('*')
            if crawl_delay:
                time_elapsed = datetime.now().timestamp() - self.last_req_ts
                if time_elapsed < crawl_delay:
                    logger.info(f'rp crawl delay wait: {url} {crawl_delay} {time_elapsed}')
                    # put back in queue or wait
                    import time
                    #time.sleep(crawl_delay - time_elapsed)

        # Exclude if domain occurrence limit is exceeded
        if self.domain_count > const.DOMAIN_LIMIT:
            logger.info(f'Domain limit exceeded: {url} {self.domain_count}')
            checked_urls_d_entry(url_dup, 'Domain limit exceeded')
            return False


    # Reuse old robots.txts to populate bot_excluder.domain_d
    def read_file():
        bot_excluder.domain_d = {}  # Default to empty
        try:
            with open(const.RP_PATH, 'rb') as rp_file:
                rp_d = pickle.load(rp_file)
                if bot_excluder.check_file_expiration(rp_d):
                    bot_excluder.domain_d = rp_d
        except Exception:
            logger.exception(f'RP file read failed:')


    def check_file_expiration(rp_d):
        # Get time robots.txt was fetched
        for i in rp_d.values():
            ts = i.rp.mtime()
            if ts: break
        else:
            logger.error('Error: cant recover any rp timestamp')
            return

        if datetime.now() - datetime.fromtimestamp(ts) > timedelta(days=const.RP_EXPIRATION_DAYS):
            logger.warning(f'rp_file outdated')
        else:
            logger.info(f'rp_file still valid')
            return True

    # Save this immediately because robots.txts expire and it's slow to req them all
    def write_file():
        with open(const.RP_PATH, 'wb') as rp_file:
            pickle.dump(bot_excluder.domain_d, rp_file)
        logger.info(f'RP file written')



class blacklist_c:
    
    # Combine recurring errors file and static blacklist
    def __init__(self):
        try:
            with open(const.AUTO_BL_PATH, "r") as f:
                self.auto_blacklist_d = json.load(f)
        except Exception:
            logger.exception(f'cant open blacklist file')
            self.auto_blacklist_d = {}

        self.purge_auto_blacklist()
        blacklist_c.combined_l = const.STATIC_BLACKLIST + tuple(self.auto_blacklist_d)


    # Remove expired entries
    def purge_auto_blacklist(self):
        rem_l = []
        for url, bl_date_s in self.auto_blacklist_d.items():
            bl_date_dt = date.fromisoformat(bl_date_s)
            if bl_date_dt + timedelta(days=const.BLACKLIST_EXPIRATION_DAYS) > date.today():
                rem_l.append(url)

        # Remove after iteration
        for url in rem_l:
            logger.info(f'Removing expired auto blacklist entry: {url} {bl_date_s}')
            del self.auto_blacklist_d[url]


    # Get recurring error URLs and add them to existing dict
    def update_auto_blacklist(self):
        for url in err_parse.rec_errs_l:
            url_dup = dup_checker(url)
            self.auto_blacklist_d[url_dup] = date.today().isoformat()

        with open(const.AUTO_BL_PATH, "w") as f:
            json.dump(self.auto_blacklist_d, f, indent=2)


# Dirs for results
def make_dirs():
    for db in const.DB_TYPES:
        db_path = os.path.join(const.RESULTS_PATH, db)
        if not os.path.exists(db_path):
            os.makedirs(db_path)

    # Dir for rp and autoblacklist files
    if not os.path.exists(const.PERSISTENT_PATH):
        os.makedirs(const.PERSISTENT_PATH)

    # Dir for error 7 files
    if not os.path.exists(const.ERR7_PATH):
        os.makedirs(const.ERR7_PATH)
        

# Resume by reading saved objs
def recover_prog():
    # pickle queue of class objs
    with open(const.QUEUE_PATH, "rb") as f:
        scrape_c.all_urls_q = pickle.load(f)
    scrape_c.total_count = scrape_c.all_urls_q.qsize()
    
    # errorlog as dict
    with open(const.ERROR_PATH, "r") as f:
        scrape_c.error_urls_d = json.load(f)
    logger.info(f'errorlog recovery complete')

    # CML as dict
    with open(const.CHECKED_PATH, "r") as f:
        scrape_c.checked_urls_d = json.load(f)
    logger.info(f'CML recovery complete')

    # multi_org_d as dict
    with open(const.MULTI_ORG_D_PATH, "r") as f:
        scrape_c.multi_org_d = json.load(f)
    logger.info(f'scrape_c.multi_org_d recovery complete')

    logger.info(f'Progress recovery successful')


# New session
def start_fresh():
    logger.info(f'Using an original queue')

    scrape_c.checked_urls_d = {}  # URLs that have been checked and their outcome (jbw conf, redirect, or error)
    scrape_c.error_urls_d = {}  # URLs that have resulted in an error
    scrape_c.multi_org_d = {'civ': {}, 'sch': {}, 'uni': {}}  # Nested dicts for multiple orgs covered by a URL
    scrape_c.all_urls_q = asyncio.Queue()

    civ_db, sch_db, uni_db = read_dbs()

    for db, db_label in (civ_db, 'civ'), (sch_db, 'sch'), (uni_db, 'uni'):
        init_queue(db, db_label)

    scrape_c.total_count = scrape_c.all_urls_q.qsize()


# Get starting urls from file
def read_dbs():
    with open(const.CIV_DB_PATH, 'r') as f:
        civ_db = json.load(f)
    with open(const.SCH_DB_PATH, 'r') as f:
        sch_db = json.load(f)
    with open(const.UNI_DB_PATH, 'r') as f:
        uni_db = json.load(f)

    # Testing purposes
    '''
    civ_db = [
    ["City of Albany", "https://jobs.albanyny.gov/jobopps", "http://www.albanyny.org"],
    ["City of Amsterdam", "https://www.amsterdamny.gov/Jobs.aspx", "http://www.amsterdamny.gov/"],
    ["City of fake", "https://jobs.albadfdggdgnyny.gov/jobopps", "http://www.albanyny.org"],
    ["Village of Fort Plain", "https://www.fortplain.org/contact-us/employment/", "https://www.fortplain.org/contact-us/employment/"]
    ]
    sch_db = []
    uni_db = []
    '''

    return civ_db, sch_db, uni_db


# Put starting URLs into the queue
def init_queue(db, db_label):
    for org_name, em_url, homepage in db:

        # Skip if em URL is missing or marked
        if not em_url: continue
        if em_url.startswith('_'): continue

        url_dup = dup_checker(em_url)

        # If that url is already in queue then mark it as multi org. After scraper copy results to all other orgs using that url
        try:
            scrape_c.multi_org_d[db_label][url_dup].append(org_name)  # Not first org using this URL
            logger.debug(f'Putting in multi org dict: {em_url}')
        except KeyError:
            scrape_c.multi_org_d[db_label][url_dup] = [org_name]  # First org using this URL

            # Put org name, em URL, initial crawl level, homepage, and jbws type into queue
            scrap = scrape_c(org_name, em_url, 0, homepage, db_label, url_dup, 0)
            proceed(em_url)  # respect robots.txt
            scrape_c.all_urls_q.put_nowait(scrap)



# Convert CML and errorlog to pretty format that can be read by humans and json
def make_human_readable(arg_dict, path):
    text = '{\n'
    for k, v in arg_dict.items(): text += json.dumps(k) + ': ' + json.dumps(v) + ',\n\n' # json uses double quotes
    text = text[:-3] # Remove trailing newlines and comma
    text += '\n}'
    with open(path, 'w', encoding='utf8') as out_file:
        out_file.write(text)


# Stop timer and display stats
def display_stats():
    duration = datetime.now() - startTime
    logger.info(f'\n\nPages checked = {len(scrape_c.checked_urls_d)}')
    logger.info(f'Duration = {round(duration.seconds / 60)} minutes')
    logger.info(f'Pages/sec/tasks = {str((len(scrape_c.checked_urls_d) / duration.seconds) / const.SEMAPHORE)[:4]} \n')


# Allow one URL to cover multiple orgs
def multi_org_copy():
    file_count = 0
    org_count = 0
    for db_type, url_d in scrape_c.multi_org_d.items():
        for url, org_names_l in url_d.items():

            # URL is used by more than one org
            if len(org_names_l) > 1:
                src_path = os.path.join(const.RESULTS_PATH, db_type, org_names_l[0])  # Path to results of first org in list

                # Check if results exists for first org
                if os.path.isdir(src_path):
                    logger.debug(f'Copying: {src_path}')

                    # Copy results from first org to all remaining orgs
                    for dst_path in org_names_l[1:]:
                        dst_path = os.path.join(const.RESULTS_PATH, db_type, dst_path)
                        logger.debug(f'to:      {dst_path}')
                        try: shutil.copytree(src_path, dst_path)
                        except Exception: logger.exception(f'multiorg copy error')
                        file_count += 1
                    org_count += 1

                # this acts like a portal error for all other orgs in this list too. can also find these errors by finding multi_d orgs in the errorlog
                # Detect no results for first multi_d org
                else:
                    logger.info(f'multi_org portal errors: {org_names_l}')
    logger.info(f'\nMulti orgs: {org_count}')
    logger.info(f'Multi org files: {file_count}')


# Fallback to older results if newer results are missing
def fallback_old_copy():
    dater_d = glob.glob(const.JORB_HOME_PATH + "/*")  # List all date dirs
    dater_d.sort(reverse=True)
    if len(dater_d) > 1:  # Skip if there are no old results
        logger.info(f'\nFalling back to old results: {dater_d[1]}')
        old_dater_results_dir = os.path.join(dater_d[1], 'results')
        count = 0

        # Loop through each results dir
        for each_db in const.DB_TYPES:

            # Select old and current db dirs
            cur_db_dir = os.path.join(const.RESULTS_PATH, each_db)
            old_db_dir = os.path.join(old_dater_results_dir, each_db)
            inc_old_dir = os.path.join(const.RESULTS_PATH, 'include_old', each_db)

            # Loop through each org name dir in the old db type dir
            for old_org_name_path in glob.glob(old_db_dir + '/*'):
                old_org_name = old_org_name_path.split('/')[-1]  # Remove path from org name

                # Check current db dir
                for cur_org_name_path in glob.glob(cur_db_dir + '/*'):

                    # Skip if the new dir has the result
                    cur_org_name = cur_org_name_path.split('/')[-1]
                    if old_org_name == cur_org_name:
                        break

                # If new org name dir is missing
                else:
                    inc_org_name_path = inc_old_dir + '/' + old_org_name  # Make old_include/old_org_name dir

                    # Copy old org name dir to db type include_dir
                    if not os.path.exists(inc_org_name_path):
                        shutil.copytree(old_org_name_path, inc_org_name_path)
                        count += 1
                        logger.debug(f'Copied fallback result: {old_org_name}')

                    # Catch errors
                    else:
                        logger.info(f'Already exists: {inc_org_name_path}')

    logger.info(f'Files in /include_old: {count}')



# Copy results to remote server using bash
def send_to_server():
    cmd_proc = subprocess.run(const.PUSH_RESULTS_PATH, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    logging.info(cmd_proc.stdout)




# Append asyncio task id if available to log
class context_filter(logging.Filter):
    def filter(self, record):
        try:
            record.task_id = f'- {asyncio.current_task().get_name()}'
        except:
            record.task_id = ''
        return True


# Config logging
logger = logging.getLogger()
def config_logger():
    logger.setLevel(logging.DEBUG)

    f_handler = logging.FileHandler(const.LOG_PATH, mode='a')
    f_handler.setLevel(logging.DEBUG)
    f_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s %(task_id)s', datefmt='%H:%M:%S')
    f_handler.setFormatter(f_format)
    f_handler.addFilter(context_filter())

    c_handler = logging.StreamHandler()
    c_handler.setLevel(logging.INFO)
    c_format = logging.Formatter('%(levelname)s - %(message)s')
    c_handler.setFormatter(c_format)

    logger.addHandler(f_handler)
    logger.addHandler(c_handler)


# Handle uncaught exceptions
def uncaught_handler(exctype, value, tb):
    logger.critical(f'------- UNCAUGHT {exctype}, {value}, {tb.tb_lineno}')
#sys.excepthook = uncaught_handler





if __name__ == '__main__':
    make_dirs()
    config_logger()
    blacklist_o = blacklist_c()
    bot_excluder.read_file()

    # Resume scraping using leftover results from the previously failed scraping attempt
    try:
        recover_prog()
    # Use original queue on any resumption error
    except Exception as errex:
        logger.info(f'{errex}')
        start_fresh()
        
    bot_excluder.write_file()  ## call this after scraper or immediatly after rp gets updated?

    asyncio.run(main(), debug=False)

    display_stats()
    multi_org_copy()
    fallback_old_copy()

    send_to_server()

    import err_parse
    blacklist_o.update_auto_blacklist()
    make_human_readable(scrape_c.checked_urls_d, const.CHECKED_PATH)
    make_human_readable(scrape_c.error_urls_d, const.ERROR_PATH)





















