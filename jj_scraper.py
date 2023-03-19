
# Description: Crawl and scrape the visible text from NYS civil service and school webpages


version_path = '/home/joepers/code/jj_v3.2'



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
from math import sin, cos, sqrt, atan2, radians
from playwright.async_api import async_playwright, TimeoutError
from urllib import parse, robotparser




startTime = datetime.now()


# Date dir to put results into
jorb_home = '/home/joepers/joes_jorbs'
dater = date.today().isoformat()
dater_path = os.path.join(jorb_home, dater)
results_path = os.path.join(dater_path, 'results')

db_types = ('civ', 'sch', 'uni')
for db in db_types:
    db_path = os.path.join(results_path, db)
    if not os.path.exists(db_path):
        os.makedirs(db_path)


# Dir for rp and autoblacklist files
persistent_path = os.path.join(jorb_home, '.persistent')
if not os.path.exists(persistent_path):
    os.makedirs(persistent_path)


# Append asyncio task id if available to log
class context_filter(logging.Filter):
    def filter(self, record):
        try:
            record.task_id = '- ' + asyncio.current_task().get_name()
        except:
            record.task_id = ''
        return True

# Config logging
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

log_path = os.path.join(dater_path, 'log_file')
f_handler = logging.FileHandler(log_path, mode='a')
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
sys.excepthook = uncaught_handler





# The webpage object
class working_c:
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
            self.jbws_high_conf = jbws_civ_high
            self.jbws_low_conf = jbws_civ_low
        else:
            self.jbws_high_conf = jbws_su_high
            self.jbws_low_conf = jbws_su_low

    # After successful request
    def add_html(self, html, vis_text, red_url, browser):
        self.html = html
        self.vis_text = vis_text.lower()
        self.red_url = red_url
        self.browser = browser
        self.soup = BeautifulSoup(html, 'html5lib').find('body')
        logger.debug(f'added html: {red_url}')

    # Print important attributes
    def __str__(self):
        return f'{self.org_name} {self.workingurl} {self.current_crawl_level} {self.parent_url} {self.jbw_type} {self.workingurl_dup} {self.req_attempt_num} {self.domain} {self.dup_domain}'

    # Get important attributes
    def clean_return(self):
        return self.org_name, self.workingurl, self.current_crawl_level, self.parent_url, self.jbw_type, self.workingurl_dup, self.req_attempt_num


    # Add new working_o to the queue
    def add_to_queue(self):

        checked_urls_d_entry(self.workingurl_dup, None)  # Add new entry to CML

        # Create new working list: [org name, URL, crawl level, parent URL, jbw type, url_dup, req attempt]
        new_working_o = working_c(self.org_name, self.workingurl, self.current_crawl_level, self.parent_url, self.jbw_type, self.workingurl_dup, 0)
        logger.debug(f'Putting list into queue: {new_working_o}')
        logger.debug(f'From: {self.parent_url}')

        # Put new working list in queue
        try:
            #with q_lock:
            all_urls_q.put_nowait(new_working_o)
            working_c.total_count += 1
        except Exception:
            logger.exception(f'__Error trying to put into all_urls_q: {new_working_o}')


    # Mark errorlog portal url entry as successful fallback. ie: portal failed so now using homepage instead. don't count as portal error
    def fallback_success(self):
        if self.current_crawl_level < 0:
            try:
                logger.info(f'Homepage fallback success: Overwriting parent_url error: {self.parent_url}')
                #with err_lock:
                error_urls_d[self.parent_url][-1].append('fallback_success')
            except KeyError:
                logger.exception(f'__error parent url key not in error_urls_d {self.parent_url}')
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


    # Reduce excess whitespace with regex and check for minimum content
    def check_vis_text(self):

        self.vis_text = re.sub(white_reg, " ", self.vis_text)

        # Skip if there is no useable visible text / soft 404s
        if len(self.vis_text) < empty_cutoff:

            # Mark error
            logger.warning(f'jj_error 7: Empty vis text: {self.workingurl} {len(self.vis_text)}')
            add_errorurls(self, 'jj_error 7', 'Empty vis text', False)

            # Debug err7
            url_path = parse.quote(self.workingurl, safe=':')
            html_path = os.path.join(err7_path, url_path)
            with open(html_path[:254], "w", encoding='ascii', errors='ignore') as write_html:
                write_html.write(self.vis_text)

            # Dont retry
            return False

        # Success
        else:
            return True

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

        ## combine this with fallback detection earlier?
        # Dont save results if this a fallback homepage
        if self.current_crawl_level < 0:
            return

        # Make dir
        org_path = os.path.join(results_path, self.jbw_type, self.org_name)
        if not os.path.exists(org_path):
            os.makedirs(org_path)

        # Make filename
        url_path = parse.quote(self.workingurl, safe=':')  # Replace forward slashes so they aren't read as directory boundaries
        html_path = os.path.join(org_path, url_path)[:254]  # max length is 255 chars

        # Make file content. Separate with ascii delim char
        file_contents_s = f'{self.jbw_count} \x1f {self.browser} \x1f {self.vis_text}'

        # Write text to file
        with open(html_path, "w", encoding='ascii', errors='ignore') as write_html:
            write_html.write(file_contents_s)
        logger.info(f'Success: Write: {url_path}')



# Removes extra info from urls to prevent duplicate pages from being checked more than once
def dup_checker(url):

    # Remove scheme and fragments
    url_dup = url.split('://')[1].split('#')[0]

    # Remove www subdomains. This works with variants like www3. 
    if url_dup.startswith('www'): url_dup = url_dup.split('.', maxsplit=1)[1]

    url_dup = url_dup.replace('//', '/') # Remove double forward slashes outside of scheme
    url_dup = url_dup.strip(' \t\n\r/') # Remove trailing whitespace and slash

    return url_dup.lower()


# Entrypoint into CML
def checked_urls_d_entry(url_dup, *args):
    #with check_lock:
    checked_urls_d[url_dup] = args
    logger.debug(f'Updated outcome for/with: {url_dup} {args}')


# Determine if url should be requested
def proceed(url) -> bool:

    # No scheme
    if not url.startswith('http://') and not url.startswith('https://'):
        logger.warning(f'__Error No scheme at: {url}')
        return False  # Declare not to proceed
        
    url_dup = dup_checker(url)

    # Exclude checked pages
    if url_dup in checked_urls_d:
        logger.debug(f'Skipping: {url_dup}')
        return False

    # Get domain info and rp
    dup_domain = url_dup.split('/')[0]  # Excludes scheme and www
    if dup_domain in domain_c.domain_d:
        domain_o = domain_c.domain_d[dup_domain]
    else:
        domain_o = domain_c(url, dup_domain)

    # Can fetch
    if domain_o.rp and len(domain_o.rp.__str__()) > 1:
        if not domain_o.rp.can_fetch('*', url):
            logger.info(f'rp can not fetch: {url}')
            return False

        # Domain rate limiter
        crawl_delay = domain_o.rp.crawl_delay('*')
        if crawl_delay:
            time_elapsed = datetime.now().timestamp() - domain_o.last_req_ts
            if time_elapsed < crawl_delay:
                logger.info(f'rp crawl delay wait: {url_dup} {crawl_delay} {time_elapsed}')
                # put back in queue or wait
                import time
                #time.sleep(crawl_delay - time_elapsed)

    # Exclude if domain occurrence limit is exceeded
    if domain_o.domain_count > domain_limit:
        logger.info(f'Domain limit exceeded: {url_dup} {domain_o.domain_count}')
        checked_urls_d_entry(url_dup, 'Domain limit exceeded')
        return False


    # Exclude if the new_url is on the blacklist
    if url_dup in blacklist:
        logger.info(f'Blacklist invoked: {url_dup}')
        checked_urls_d_entry(url_dup, 'Blacklist invoked')
        return False

    # Declare to proceed
    return True


# Get working list from queue
async def get_working_o(task_id):
    try:
        async with q_lock:
            working_o = all_urls_q.get_nowait()
            all_done_d[task_id] = False
        return working_o

    # Empty queue
    except asyncio.QueueEmpty:
        logger.info(f'queue empty')
        all_done_d[task_id] = True
        await asyncio.sleep(8)

    except Exception:
        logger.exception(f'QUEUE __ERROR:')
        await asyncio.sleep(8)


# Choose requester based on attempt number
async def choose_requester(working_o, task_id, pw, session):
    working_o.req_attempt_num += 1
    try:
        if working_o.req_attempt_num < 3:
            await pw_req(working_o, task_id, pw)
        elif working_o.req_attempt_num < 5:
            await asyncio.wait_for(static_req(working_o, task_id, session), timeout=30)
        else:
            logger.info(f'All retries exhausted: {working_o.workingurl} {working_o.req_attempt_num}')
            working_c.prog_count += 1

    except asyncio.TimeoutError as errex:
        logger.warning(f'looper timeout __error: {errex} {working_o}')
        add_errorurls(working_o, 'jj_error 8', 'looper timeout', True)

    except Exception as errex:
        logger.exception(f'looper __error: {sys.exc_info()[2].tb_lineno}')
        add_errorurls(working_o, 'jj_error 9', errex, True)
            

# Decide which requester to use based on number of attmepts for that URL
async def looper(pw, session):
    task_id = asyncio.current_task().get_name()

    # End looper if all tasks report empty queue
    while not all(all_done_d.values()):

        # Check internet connectivity
        while pw_pause:
            logger.warning(f'pw_pause invoked')
            await asyncio.sleep(4)

        # Get working list from queue
        working_o = await get_working_o(task_id)
        if not working_o: continue
        logger.debug(f'got new working_list {working_o}')

        # Make request
        await choose_requester(working_o, task_id, pw, session)

        # Success
        if hasattr(working_o, 'html'):
            req_success(working_o)

        #else: handle errors from both requesters here?

    # All tasks complete
    logger.info(f'Task complete:')


# After successful webpage retrieval
def req_success(working_o):
    logger.debug(f'has html: {working_o.workingurl}')
    working_c.prog_count += 1
    
    logger.debug(f'begin domain_o.update {working_o} {domain_c.domain_d[working_o.dup_domain]}')
    domain_c.domain_d[working_o.dup_domain].update()  # Inc domain_count
    
    logger.debug(f'begin fallback_success {working_o}')
    working_o.fallback_success()  # Check and update fallback
    
    working_o.count_jbws()
    checked_urls_d_entry(working_o.workingurl_dup, working_o.jbw_count, working_o.browser)  # Update outcome in checked_urls_d

    logger.debug(f'begin check_red {working_o}')
    if not working_o.check_red():  # Check if redirect URL has been processed already
        logger.info(f'check_red fail {working_o}')
        return

    logger.debug(f'begin check_vis_text {working_o}')
    if not working_o.check_vis_text():  # Check for minimum content/soft 404
        return

    working_o.write_results()  # Write result text to file
    crawler(working_o)  # Get more links from page


# Select pw browser, create context and page
async def get_pw_brow(pw, task_id):
    for brow in brow_l:
        try:
            context = await brow.new_context(ignore_https_errors=True)  ## slow execution here?
            logger.debug(f'here3')
            context.set_default_timeout(20000)
            page = await context.new_page()
            logger.debug(f'using brow: {brow._impl_obj._browser_type.name}')
            return context, page

        # Remove browser from available list on error
        except Exception:
            logger.exception(f'error creating context or page')
            await clear_brows(pw, brow)

    # No browser available
    else:
        logger.warning(f'brow list empty')
        await asyncio.sleep(4)


# Playwright requester
@timeout_decorator.timeout(20)
async def pw_req(working_o, task_id, pw):
    logger.debug(f'here1')
    # Select pw browser, context, and page
    context, page = await get_pw_brow(pw, task_id)
    # Request URL
    try:
        workingurl = working_o.workingurl
        logger.debug(f'start pw req: {workingurl}')
        resp = await page.goto(workingurl)
        #await resp.finished()
        await page.wait_for_load_state('networkidle')
        logger.debug(f'end pw req: {workingurl}')
        logger.debug(f'req timer: {resp.request.timing["responseEnd"]}')


        # Forbidden content types. only works with firefox
        if 'application/pdf' in resp.headers['content-type']:
            logger.info(f'jj_error 2: Forbidden content type:')
            add_errorurls(working_o, 'jj_error 2', 'Forbidden content type', False)
            return

        stat_code = resp.status
        stat_text = f'{stat_code} {resp.status_text}'
        red_url = resp.url

        # Success
        if stat_code == 200:
            logger.info(f'pw req success {workingurl}')

            # Get child frame content recursively
            try:
                logger.debug(f'begin frame loop: {workingurl} {len(page.frames)}')
                ret_t = await asyncio.wait_for(child_frame(page.main_frame, task_id), timeout=3)  # Prevent child frames from hanging forever
                html = '\n' + ret_t[0]
                vis_text = '\n' + ret_t[1]
                logger.debug(f'end frame loop: {workingurl}')

            # Fallback to html without child frame content
            except asyncio.TimeoutError:
                logger.warning(f'child frame timeout {workingurl}')
                html = await page.content()
                vis_text = await page.inner_text('body')
            ## redundant?
            except Exception as errex:
                logger.warning(f'other child frame __error: {errex} {workingurl}')
                html = await page.content()
                vis_text = await page.inner_text('body')

            finally:
                working_o.add_html(html, vis_text, red_url, 'pw_browser')

        # Request errors
        # Don't retry
        elif stat_code == 404 or stat_code == 403:
            logger.warning(f'jj_error 4: {workingurl} {stat_text}')
            add_errorurls(working_o, 'jj_error 4', stat_text, False)

        # Retry
        else:
            logger.warning(f'jj_error 5: request error: {workingurl} {stat_text}')
            add_errorurls(working_o, 'jj_error 5', stat_text, True)
            if stat_code == 429:
                logger.warning(f'__error 429 {workingurl}')
                await asyncio.sleep(4)

    # Timeout
    except TimeoutError:
        logger.warning(f'jj_error 3: Timeout {workingurl}')
        add_errorurls(working_o, 'jj_error 3', 'Timeout', True)

    # Error
    except Exception as errex:
        logger.warning(f'jj_error 6: playwright error: {workingurl} {sys.exc_info()[2].tb_lineno}')
        add_errorurls(working_o, 'jj_error 6', str(errex), True)

    # Close and return
    finally:
        try:
            await context.close()
        except Exception:
            logger.exception(f'cant close context')


# Recursive child frame explorer
async def child_frame(frame, task_id):
    try:

        # Discard useless frames
        if frame.name == "about:srcdoc" or frame.name == "about:blank" or not frame.url or frame.url == "about:srcdoc" or frame.url == "about:blank" or frame.is_detached():
            return "", ""

        # Current frame content
        html = await frame.content()
        vis_text = await frame.inner_text('body')

        # Get child frame content
        #logger.debug(f'num child frames: {len(frame.child_frames)} {frame}')
        for c_f in frame.child_frames:
            ret_t = await child_frame(c_f, task_id)
            html += '\n' + ret_t[0]
            vis_text += '\n' + ret_t[1]
            logger.debug(f'child frame appended: {frame.url}')

        return html, vis_text

    except Exception as errex:
        logger.warning(f'child_frame_f __error: {errex}')
        return "", ""


# Static requester
async def static_req(working_o, task_id, session):

    workingurl = working_o.workingurl

    try:
        logger.debug(f'start static req: {workingurl}')
        async with session.get(workingurl, headers={'User-Agent': user_agent_s}, ssl=False) as resp:
            logger.debug(f'end static req: {workingurl}')

            # Must detect forbidden content types before getting html
            if 'application/pdf' in resp.headers['content-type']:
                logger.info(f'jj_error 2b: Forbidden content type:')
                add_errorurls(working_o, 'jj_error 2b', 'Forbidden content type (static)', False)
                return

            html = await resp.text()
            red_url = str(resp.url)
            stat_code = resp.status
            stat_text = f'{stat_code} {resp.reason}'

            # Success
            if stat_code == 200:
                logger.info(f'Static req success: {workingurl} {stat_code}')
                working_o.add_html(html, vis_text, red_url, 'static_browser')
                vis_text = vis_soup(html)  # Get vis soup

            # Don't retry
            elif stat_code == 404 or stat_code == 403:
                logger.warning(f'jj_error 4b: {workingurl} {stat_text}')
                add_errorurls(working_o, 'jj_error 4b', stat_text, False)

            # Retry
            else:
                logger.warning(f'jj_error 5b: request error: {workingurl} {stat_text}')
                add_errorurls(working_o, 'jj_error 5b',  stat_text, True)

    except asyncio.TimeoutError:
        logger.warning(f'jj_error 3b: Timeout {workingurl}')
        add_errorurls(working_o, 'jj_error 3b', 'Timeout', True)

    except Exception as errex:
        logger.warning(f'jj_error 6b: Other Req {workingurl}')
        add_errorurls(working_o, 'jj_error 6b', str(errex), True)

    finally:
        return True



# url: [[org name, db type, crawl level], [[error number, error desc], [error number, error desc]], [final error flag, fallback flags]]
# Append URLs and info to the errorlog. Allows multiple errors (values) to each URL (key)
def add_errorurls(working_o, err_code, err_desc, back_in_q_b):
    org_name, workingurl, current_crawl_level, parent_url, jbw_type, workingurl_dup, req_attempt_num = working_o.clean_return()

    ## errorlog splits should use non printable char
    # Remove commas from text to prevent splitting errors when reading errorlog
    err_desc = err_desc.replace(',', '').strip()

    # First error for this url
    if not workingurl in error_urls_d:
        #with err_lock:
        error_urls_d[workingurl] = [[org_name, jbw_type, current_crawl_level], [[err_desc, err_code]]]

    # Not the first error for this url
    else:
        try:
            #with err_lock:
            error_urls_d[workingurl][1].append([err_desc, err_code])
        except Exception:
            logger.exception(f'Cant append error to errorlog: {workingurl}')

    # Add URL back to queue
    if back_in_q_b:
        logger.debug(f'Putting back into queue: {workingurl}')
        #with q_lock:
        all_urls_q.put_nowait(working_o)

    # Add final_error flag to errorlog
    else:
        final_error(working_o)

    ## should this be called only on final error or success?
    # Update checked pages value to error code
    checked_urls_d_entry(workingurl_dup, err_code)
    return True


# Mark final errors in errorlog
def final_error(working_o):
    org_name, workingurl, current_crawl_level, parent_url, jbw_type, workingurl_dup, req_attempt_num = working_o.clean_return()
    try:
        working_c.prog_count += 1
        #with err_lock:
        error_urls_d[workingurl].append(['jj_final_error'])

        # If request failed on first URL (portal), use homepage as fallback
        if current_crawl_level == 0:
            logger.info(f'Using URL fallback: {parent_url}')

            # Put homepage url into queue with -1 current crawl level
            if proceed(parent_url):
                working_o.workingurl = parent_url
                working_o.current_crawl_level = -1
                working_o.parent_url = workingurl  ## parent of homepage fallback?
                working_o.workingurl_dup = dup_checker(parent_url)
                working_o.add_to_queue()

    except Exception:
        logger.exception(f'final_e __error: {workingurl} {sys.exc_info()[2].tb_lineno}')


# Separate the visible text from HTML
def vis_soup(html):

    vis_soup = BeautifulSoup(html, 'html5lib').find('body')  # Select body

    # Remove script, style, and empty elements
    for x in vis_soup(["script", "style"]):
        x.decompose()

    ## unn
    # Remove all of the hidden style attributes
    for x in vis_soup.find_all('', {"style" : style_reg}):
        x.decompose()

    # Type="hidden" attribute
    for x in vis_soup.find_all('', {"type" : 'hidden'}):
        x.decompose()

    # Hidden section(s) and dropdown classes
    for x in vis_soup(class_=class_reg):
        x.decompose()

    return vis_soup.text



# Include pagination links
def get_pagination(working_o):
    org_name, workingurl, current_crawl_level, parent_url, jbw_type, workingurl_dup, req_attempt_num = working_o.clean_return()
    domain = working_o.domain
    soup = working_o.soup
        
    for pag_class in soup.find_all(class_='pagination'):
        logger.info(f'pagination class found: {workingurl}')
        for anchor_tag in pag_class.find_all('a'):  # Find anchor tags
            logger.info(f'anchor_tag.text {anchor_tag.text}')
            if 'next' in anchor_tag.text.lower():  # Find "next" page url

                # Add to queue
                abspath = parse.urljoin(domain, anchor_tag.get('href'))
                if proceed(abspath):
                    logger.info(f'Adding pagination url: {abspath} {workingurl}')
                    working_o.workingurl = abspath
                    working_o.workingurl_dup = dup_checker(abspath)
                    working_o.parent_url = workingurl
                    working_o.add_to_queue()

            ## look for next page button represented by angle bracket
            elif '>' in anchor_tag.text: logger.debug(f'pagination angle bracket {anchor_tag.text}')


# Find more links
def get_links(soup, jbws_high_conf, workingurl, domain):
        
    fin_urls = set()
    for anchor_tag in soup.find_all('a'):

        # Widen search of jbws if only 1 url in elem. should this be recursive? ie grandparent
        if len(anchor_tag.parent.find_all('a')) == 1:
            tag = anchor_tag.parent
        else:
            tag = anchor_tag

        # Newlines will mess up jbw and bunk detection
        for br in tag.find_all("br"):
            br.replace_with(" ")

        # Skip if the tag contains a bunkword
        if any(bunkword in str(tag).lower() for bunkword in bunkwords):
            logger.debug(f'Bunk word detected: {workingurl} {str(tag)[:99]}')
            continue

        # Skip if no jobwords in content
        ## use this for only high conf jbws
        tag_content = str(tag.text).lower()
        if not any(jbw in tag_content for jbw in jbws_high_conf):
            #logger.debug(f'No jobwords detected: {workingurl} {tag_content[:99]}')
            continue

        '''
        ## use this for either low or high conf jbws, with new low conf format
        if not any(ttt in tag_content for ttt in jbws_high_conf + jbws_low_conf):
            if working_o.jbw_type == 'civ': continue
            # Exact match only for sch and uni extra low conf jbws
            else:
                if not tag_content in jbws_su_x_low: continue
        '''        
        '''
        # Tally which jbws are used
        for i in jbws_high_conf + jbws_low_conf:
            if i in tag_content:
                async with lock: jbw_tally_ml.append(i)
        '''

        bs_url = anchor_tag.get('href')
        abspath = parse.urljoin(domain, bs_url).strip()  # Convert relative paths to absolute and strip whitespace
        logger.debug(f'abspath: {abspath} {tag_content}')
        # Remove non printed characters
        #abspath = abspath.encode('ascii', 'ignore').decode()
        #abspath = parse.quote(abspath)

        fin_urls.add(abspath)

    return fin_urls


# Explore html to find more links and weigh confidence
def crawler(working_o):
    try:
        org_name, workingurl, current_crawl_level, parent_url, jbw_type, workingurl_dup, req_attempt_num = working_o.clean_return()

        # Remove non ascii characters, strip, percent encode
        #red_url = red_url.encode('ascii', 'ignore').decode().strip()
        #red_url = parse.quote(red_url, safe='/:')

        # Search for pagination links before checking crawl level
        get_pagination(working_o)

        # Limit crawl level
        if current_crawl_level > max_crawl_depth:
            return

        logger.debug(f'Begin crawling: {workingurl}')
        working_o.current_crawl_level += 1

        # List of urls to add to queue
        fin_urls = get_links(working_o.soup, working_o.jbws_high_conf, workingurl, working_o.domain)

        # Check new URLs and append to queue
        logger.debug(f'links from {workingurl} {fin_urls}')
        for abspath in fin_urls:
            if proceed(abspath):
                #new_working_o = working_c(org_name, abspath, current_crawl_level, workingurl, db_name, dup_checker(abspath), req_attempt_num)
                working_o.workingurl = abspath
                working_o.workingurl_dup = dup_checker(abspath)
                working_o.parent_url = workingurl
                working_o.add_to_queue()

    except Exception as errex:
        logger.exception(f'\njj_error 1: Crawler error detected. Skipping... {str(traceback.format_exc())} {working_o}')
        add_errorurls(working_o, 'jj_error 1', str(errex), True)
        return



# Restart pw browsers
async def clear_brows(pw, *args):
    logger.info(f'Begin clear_brows_f {args}')

    # Manual restart
    for brow in args:
        async with brow_lock:
            brow_l.remove(brow)
        async with res_brow_lock:
            restart_brow_set.add(brow)

    # Auto restart
    for brow in brow_l:
        if not brow.is_connected():
            logger.warning(f'brow not connected {brow}')
            async with brow_lock:
                brow_l.remove(brow)
            async with res_brow_lock:
                restart_brow_set.add(brow)
    
    # Restart nonworking pw browsers
    logger.debug(f'restart_brow_set: {restart_brow_set}')
    for brow in restart_brow_set:
        brow_name = brow._impl_obj._browser_type.name

        # Wait for tasks to depopulate the browser before closing
        for i in range(20):
            if len(brow.contexts) > 0:
                logger.debug(f'cons still open open: {brow.contexts}')
                await asyncio.sleep(1)
            else:
                logger.info(f'Closing brow: {brow}')
                break
        else:
            logger.warning(f'brow depop timeout {brow}')

        # Close original browser
        await brow.close()

        # Start replacement browsers
        if brow_name == 'chromium':
            logger.debug(f'starting chromium')
            new_browser = await pw.chromium.launch(args=['--disable-gpu'])
        elif brow_name == 'firefox':
            logger.debug(f'starting firefox')
            new_browser = await pw.firefox.launch()
        else:
            logger.error(f'__error: cant detect browser name {brow} {brow_name}')
            continue

        logger.info(f'Started new brow: {new_browser}')
        async with brow_lock:
            brow_l.append(new_browser)

    # Clear restart_brow_set after iteration
    restart_brow_set.clear()


# Start primary and fallback pw browsers
async def init_pw_brows(pw):
    pw_browser = await pw.chromium.launch(args=['--disable-gpu'])
    brow_l.append(pw_browser)

    pw_browser = await pw.firefox.launch()
    brow_l.append(pw_browser)
        

# Check internet connectivity
async def ping_begin():
    ping_tally = 0
    while True:
        try:
            logger.debug(f'pw ping begin')
            brow = brow_l[0]
            context = await brow.new_context(ignore_https_errors=True)
            page = await context.new_page()
            page.set_default_timeout(5000)
            resp = await page.goto('http://joesjorbs.com')

            # Success
            if resp.status == 200:
                pw_pause = False
                logger.debug(f'pw ping success')
                return
            else:
                raise Exception('pw ping fail')

        except Exception:
            logger.exception(f'__error ping:')
            ping_tally += 1

        finally:
            try:
                await context.close()
            except Exception:
                logger.exception(f'ping: could not close context')

        # Attempt Bash ping on PW failure
        bash_ping_ret = await bash_ping()

        ## restart pw not nic if bash succeeds but pw fails
        # Restart network interface on any two errors
        if ping_tally > 1 or bash_ping_ret != 0:
            pw_pause = True
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
logger.debug(f'rec1 {sys.getrecursionlimit()}')
#sys.setrecursionlimit(50000)  # why did pickle.dump() start giving "maximum recursion depth exceeded while calling a Python object" ?
async def save_progress():
    logger.debug(f'begin prog save')
    try:
        # Pickle queue of working_os
        async with q_lock:
            with open(queue_path, "wb") as f:
                pickle.dump(all_urls_q, f)

        # CML, errorlog, and multiorg
        for each_path, each_dict in (checked_path, checked_urls_d), (error_path, error_urls_d), (multi_org_d_path, multi_org_d):
            with open(each_path, "w") as f:
                json.dump(each_dict, f)
    except Exception:
        logger.exception(f'\n prog_f __ERROR: {sys.exc_info()[2].tb_lineno}')
    logger.debug(f'prog save success')


# Restart primary pw browser when mem usage is high
async def check_mem():
    if psutil.virtual_memory()[2] > 50:
        logger.error(f'Memory usage too high. Restarting browser: {brow_l[0]}')
        await clear_brows(pw, brow_l[0])


# Display progress
def display_prog():
    logger.info(f'\nProgress: {working_c.prog_count} of {working_c.total_count}')
    logger.info(f'mem use: {psutil.virtual_memory()[2]}')
    for t_brow in brow_l:
        for t_con in t_brow.contexts:
            logger.info(f'{t_brow._impl_obj._browser_type.name} open pages: {len(t_con.pages)} {t_con.pages}')
    logger.info(f'running tasks: {len(asyncio.all_tasks())}')
    #prant('running tasks:', asyncio.all_tasks())
    logger.info(f'len(brow_l): {len(brow_l)}')
    logger.info(f'len(restart_brow_set): {len(restart_brow_set)}')


# Start scraper
async def init_async_tasks(pw, session):
    for i in range(semaphore):
        task = asyncio.create_task(looper(pw, session))
        all_done_d[task.get_name()] = False


# Main event loop
async def main():
    logger.info(f'\n Program Start')

    # Start Playwright and aiohttp
    timeout = aiohttp.ClientTimeout(total=8)
    async with async_playwright() as pw, aiohttp.ClientSession(timeout=timeout) as session:
        await init_pw_brows(pw)

        # Run scraper
        await init_async_tasks(pw, session)

        # Wait for scraping to finish
        skip_tally = 0
        while not all(all_done_d.values()):
            try:
                # Run housekeeping funcs and display progress
                for intermittent_f in save_progress, ping_begin, check_mem:
                    await intermittent_f()
                    display_prog()
                    await asyncio.sleep(8)

            except Exception:
                logger.exception(f'\nprog_f __ERROR: {sys.exc_info()[2].tb_lineno}')
                await asyncio.sleep(2)

        # Scrape complete. Close browsers
        logger.info(f'  Scrape complete  '.center(70, '='))
        await shutdown_scraper(session)


# Close browsers
async def shutdown_scraper(session):
    try:
        for i in brow_l:
            await i.close()
        await session.close()
    except Exception:
        logger.exception(f'Browser close error')











# Dir for error 7 files
err7_path = os.path.join(dater_path, 'jj_error_7')
if not os.path.exists(err7_path):
    os.makedirs(err7_path)

# Scraper options
max_crawl_depth = 1  # Webpage recursion depth
semaphore = 12  # Num of concurrent tasks
empty_cutoff = 200  # Num of characters in webpage text file to be considered empty
domain_limit = 20  # Max num of pages per domain

# Locks
q_lock = asyncio.Lock()
brow_lock = asyncio.Lock()
res_brow_lock = asyncio.Lock()
err_lock = asyncio.Lock()
check_lock = asyncio.Lock()

# For managing and restarting PW browsers
brow_l = []
restart_brow_set = set()

#jbw_tally_ml = [] # Used to determine the frequency that jbws are used (debugging)

# Set paths to files
queue_path = os.path.join(dater_path, 'queue')
checked_path = os.path.join(dater_path, 'checked_pages')
error_path = os.path.join(dater_path, 'errorlog')
multi_org_d_path = os.path.join(dater_path, 'multi_org_d')
rp_path = os.path.join(persistent_path, 'rp_file')
auto_bl_path = os.path.join(persistent_path, 'auto_blacklist')


pw_pause = False  # Tell all tasks to wait if there is no internet connectivity
all_done_d = {}  # Each task states if the queue is empty


user_agent_s = 'Mozilla/5.0 (X11; Linux x86_64; rv:103.0) Gecko/20100101 Firefox/103.0'

# Compile regex paterns for reducing whitespace in written files
white_reg = re.compile("\s{2,}")

# Compile regex paterns for removing hidden HTML elements
style_reg = re.compile("(display\s*:\s*(none|block);?|visibility\s*:\s*hidden;?)")
class_reg = re.compile('(hidden-sections?|dropdown|has-dropdown|sw-channel-dropdown|dropdown-toggle)')

## application
# Exclude links that contain any of these. percent encodings must be lower case
bunkwords = ('academics', '5il.co', '5il%2eco', 'pnwboces.org', 'recruitfront.com', 'schoolapp.wnyric.org', 'professional development', 'career development', 'javascript:', '.pdf', '.jpg', '.ico', '.rtf', '.doc', '.mp4', '%2epdf', '%2ejpg', '%2eico', '%2ertf', '%2edoc', '%2emp4', 'mailto:', 'tel:', 'icon', 'description', 'specs', 'specification', 'guide', 'faq', 'images', 'exam scores', 'resume-sample', 'resume sample', 'directory', 'pupil personnel')

# Include links that include any of these
# Set high and low confidence jbw lists
jbws_all_high = ('continuous recruitment', 'employment', 'job listing', 'job opening', 'job posting', 'job announcement', 'job opportunities', 'job vacancies', 'jobs available', 'available positions', 'open positions', 'available employment', 'career opportunities', 'employment opportunities', 'current vacancies', 'current job', 'current employment', 'current opening', 'current posting', 'current opportunities', 'careers at', 'jobs at', 'jobs @', 'work at', 'employment at', 'find your career', 'browse jobs', 'search jobs', 'vacancy postings', 'vacancy list', 'prospective employees', 'help wanted', 'work with', 'immediate opportunities', 'promotional announcements')
jbws_all_low = ('join', 'job', 'job seeker', 'job title', 'positions', 'careers', 'human resource', 'personnel', 'vacancies', 'vacancy', 'posting', 'opening', 'recruitment')

jbws_civ_high = ['upcoming exam', 'exam announcement', 'examination announcement', 'examinations list', 'civil service opportunities', 'civil service exam', 'civil service test', 'current civil service', 'open competitive', 'open-competitive']
jbws_civ_high += jbws_all_high

jbws_civ_low = ['open to', 'civil service', 'exam', 'examination', 'test', 'current exam']
jbws_civ_low += jbws_all_low

jbws_su_high = jbws_all_high
jbws_su_low = jbws_all_low
jbws_su_x_low = ('faculty', 'staff', 'adjunct', 'academic', 'support', 'instructional', 'administrative', 'professional', 'classified', 'coaching')




# robots.txt and domain tracker used for rate limiting
domain_lock = asyncio.Lock()
import ssl
ssl._create_default_https_context = ssl._create_unverified_context  ## rp.read req can throw error

class domain_c:
    domain_d = {}

    @timeout_decorator.timeout(8)
    def __init__(self, url, dup_domain):
        self.domain = '://'.join(parse.urlparse(url)[:2])  # Includes scheme and www.
        logger.info(f'new domain: {self.domain} {dup_domain}')

        self.last_req_ts = 0.0
        self.domain_count = 0

        # Get robots.txt
        try:
            self.rp = robotparser.RobotFileParser()
            self.rp.set_url(parse.urljoin(self.domain, "robots.txt"))
            self.rp.read()  # req
            logger.debug(f"rp printout: {self.rp.allow_all} {self.rp.disallow_all} {self.rp.can_fetch('*', '*')} {self.rp.url}")
        except Exception as errex :
            logger.warning(f'__error: rp read: {self.domain} {errex}')
            self.rp = None

        # Store rp so it is requested only once
        domain_c.domain_d[dup_domain] = self


    # After req
    def update(self):
        logger.debug(f"update start")
        #with domain_lock:
        self.last_req_ts = datetime.now().timestamp()
        logger.debug(f"update 1111")
        self.domain_count += 1
        logger.debug(f"update complete")



## unn?
# Omit these pages
blacklist = ['cc.cnyric.org/districtpage.cfm?pageid=112', 'co.essex.ny.us/personnel', 'co.ontario.ny.us/94/human-resources', 'countyherkimer.digitaltowpath.org:10069/content/departments/view/9:field=services;/content/departmentservices/view/190', 'countyherkimer.digitaltowpath.org:10069/content/departments/view/9:field=services;/content/departmentservices/view/35', 'cs.monroecounty.gov/mccs/lists', 'herkimercounty.org/content/departments/view/9:field=services;/content/departmentservices/view/190', 'herkimercounty.org/content/departments/view/9:field=services;/content/departmentservices/view/35', 'jobs.albanyny.gov/default/jobs', 'monroecounty.gov/hr/lists', 'monroecounty.gov/mccs/lists', 'mycivilservice.rocklandgov.com/default/jobs', 'niagaracounty.com/employment/eligible-lists', 'ogdensburg.org/index.aspx?nid=345', 'penfield.org/multirss.php', 'tompkinscivilservice.org/civilservice/jobs', 'tompkinscivilservice.org/civilservice/jobs', 'swedishinstitute.edu/employment-at-swedish-institute', 'sunyacc.edu/job-listings']

# Auto blacklist
auto_blacklist_d = {}
today_dt = date.today()

# Open existing blacklist
try:
    with open(auto_bl_path, "r") as f:
        auto_blacklist_d = json.load(f)

    # Check if entry is more than N days old
    rem_l = []
    for k, v in auto_blacklist_d.items():
        v_dt = date.fromisoformat(v)

        # Combine with blacklist
        if v_dt + timedelta(days=60) > today_dt:
            blacklist.append(k)

        # Remove expired entries
        else:
            logger.info(f'Removing expired auto blacklist entry: {k} {v}')
            rem_l.append(k)

    for i in rem_l:
        del auto_blacklist_d[i]

except Exception:
    logger.exception(f'cant open blacklist:')


# Read rp file
try:
    with open(rp_path, 'rb') as rp_file:
        rp_d = pickle.load(rp_file)

    # Get time robots.txt was fetched
    for i in rp_d.values():
        ts = i.rp.mtime()
        if ts: break
    else:
        logger.error('Error: cant recover timestamp')

    logger.info(f'rp_file recovery complete')
    if datetime.now() - datetime.fromtimestamp(ts) > timedelta(days=90):
        logger.warning(f'rp_file outdated: {datetime.fromtimestamp(ts).isoformat()}')
    else:
        domain_c.domain_d = rp_d
        logger.info(f'rp_file still valid: {datetime.fromtimestamp(ts).isoformat()}')
except Exception:
    logger.exception(f'RP file read failed:')


# Resume scraping using leftover results from the previously failed scraping attempt
try:

    # Read pickle queue of class objs
    with open(queue_path, "rb") as f:
        all_urls_q = pickle.load(f)

    # Read errorlog file as dict
    with open(error_path, "r") as f:
        error_urls_d = json.load(f)
    logger.info(f'errorlog recovery complete')

    # Read CML file as dict
    with open(checked_path, "r") as f:
        checked_urls_d = json.load(f)
    logger.info(f'CML recovery complete')

    # Read multi_org_d file as dict
    with open(multi_org_d_path, "r") as f:
        multi_org_d = json.load(f)
    logger.info(f'multi_org_d recovery complete')

    working_c.total_count = all_urls_q.qsize()
    logger.info(f'File queue success')


# Use original queue on any resumption error
except Exception as errex:
    logger.info(f'Using an original queue {errex}')

    checked_urls_d = {}  # URLs that have been checked and their outcome (jbw conf, redirect, or error)
    error_urls_d = {}  # URLs that have resulted in an error


    # Read DBs
    with open(os.path.join(version_path, 'dbs/civ_db'), 'r') as f:
        civ_db = json.load(f)
    with open(os.path.join(version_path, 'dbs/sch_db'), 'r') as f:
        sch_db = json.load(f)
    with open(os.path.join(version_path, 'dbs/uni_db'), 'r') as f:
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

    # Nested dicts for multiple orgs covered by a URL
    multi_org_d = {}
    multi_org_d['civ'] = {}
    multi_org_d['sch'] = {}
    multi_org_d['uni'] = {}

    # Put all URLs into the queue
    all_urls_q = asyncio.Queue()
    for db, db_name in (civ_db, 'civ'), (sch_db, 'sch'), (uni_db, 'uni'):
        for org_name, em_url, homepage in db:

            # Skip if em URL is missing or marked
            if not em_url: continue
            if em_url.startswith('_'): continue

            url_dup = dup_checker(em_url)

            # URL as key, all org names using that URL as values
            try:
                multi_org_d[db_name][url_dup].append(org_name)  # Not first org using this URL
                logger.debug(f'Putting in multi org dict: {em_url}')
            except KeyError:
                multi_org_d[db_name][url_dup] = [org_name]  # First org using this URL
                #checked_urls_d_entry(url_dup, None)

                # Put org name, em URL, initial crawl level, homepage, and jbws type into queue
                working_o = working_c(org_name, em_url, 0, homepage, db_name, url_dup, 0)
                proceed(em_url)  # respect robots.txt
                all_urls_q.put_nowait(working_o)

        db = None  # Clear
        working_c.total_count = all_urls_q.qsize()



# Write RP to file
with open(rp_path, 'wb') as rp_file:
    pickle.dump(domain_c.domain_d, rp_file)







# Start async event loop
asyncio.run(main(), debug=False)






'''
# jbw tally
for i in jbws_civ_low:
    r_count = jbw_tally_ml.count(i)
    logger.info(f'{i} = {r_count}')
for i in jbws_su_low:
    r_count = jbw_tally_ml.count(i)
    logger.info(f'{i} = {r_count}')
for i in jbws_civ_high:
    r_count = jbw_tally_ml.count(i)
    logger.info(f'{i} = {r_count}')
for i in jbws_su_high:
    r_count = jbw_tally_ml.count(i)
    logger.info(f'{i} = {r_count}')
'''



# Convert CML and errorlog to nice format that can be read by humans and json
## this prevents resumption because json converts None to null: NameError: name 'null' is not defined
cml_text = '{\n'
for k, v in checked_urls_d.items(): cml_text += json.dumps(k) + ': ' + json.dumps(v) + ',\n\n' # json uses double quotes
cml_text = cml_text[:-3] # Delete trailing newlines and comma
cml_text += '\n}'
with open(checked_path, 'w', encoding='utf8') as checked_file:
    checked_file.write(cml_text)

# Write errorlog
# url: [[org name, db type, crawl level], [[error number, error desc], [error number, error desc]], [final error flag, fallback flags]]
e_text = '{\n'
for k, v in error_urls_d.items(): e_text += json.dumps(k) + ': ' + json.dumps(v) + ',\n\n'
e_text = e_text[:-3]
e_text += '\n}'
with open(error_path, 'w', encoding='utf8') as error_file:
    error_file.write(e_text)



# Stop timer and display stats
duration = datetime.now() - startTime
logger.info(f'\n\nPages checked = {len(checked_urls_d)}')
logger.info(f'Duration = {round(duration.seconds / 60)} minutes')
logger.info(f'Pages/sec/tasks = {str((len(checked_urls_d) / duration.seconds) / semaphore)[:4]} \n')


'''
##
# Delete queue.txt to indicate program completed successfully
try:
    os.remove(queue_path)
    logger.info(f'\nDeleted queue_path file\n')
except:
    logger.info(f'\nFailed to delete queue_path file\n')
'''








# Allow one URL to cover multiple orgs
file_count = 0
org_count = 0
for db_type, url_d in multi_org_d.items():

    for url, org_names_l in url_d.items():

        # URL is used by more than one org
        if len(org_names_l) > 1:

            src_path = os.path.join(results_path, db_type, org_names_l[0])  # Path to results of first org in list

            # Check if results exists for first org
            if os.path.isdir(src_path):
                logger.debug(f'Copying: {src_path}')

                # Copy results from first org to all remaining orgs
                for dst_path in org_names_l[1:]:
                    dst_path = os.path.join(results_path, db_type, dst_path)
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
dater_d = glob.glob(jorb_home + "/*")  # List all date dirs
dater_d.sort(reverse=True)
if len(dater_d) > 1:  # Skip if there are no old results
    logger.info(f'\nFalling back to old results: {dater_d[1]}')
    old_dater_results_dir = os.path.join(dater_d[1], 'results')
    count = 0

    # Loop through each results dir
    for each_db in db_types:

        # Select old and current db dirs
        cur_db_dir = os.path.join(results_path, each_db)
        old_db_dir = os.path.join(old_dater_results_dir, each_db)
        inc_old_dir = os.path.join(results_path, 'include_old', each_db)

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
cmd_proc = subprocess.run(os.path.join(version_path, "push_results.sh"), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
logging.info(cmd_proc.stdout)



# Auto blacklist
# Get recurring error URLs and add them to existing dict
import err_parse

for url in err_parse.rec_errs_l:
    url_dup = dup_checker(url)
    auto_blacklist_d[url_dup] = today_dt.isoformat()

# Write file
with open(auto_bl_path, "w") as f:
    json.dump(auto_blacklist_d, f, indent=2)





