
# Description: Crawl and scrape the visible text from NYS civil service and school webpages

version = '3.2'





import aiohttp, asyncio, glob, json, os, pickle, psutil, re, shutil, sys, subprocess, traceback, urllib.robotparser
from urllib import parse
from datetime import datetime, timedelta, date
from math import sin, cos, sqrt, atan2, radians
#from http.cookiejar import CookieJar
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, TimeoutError
import timeout_decorator




startTime = datetime.now()  # Start timer

user_agent_s = 'Mozilla/5.0 (X11; Linux x86_64; rv:103.0) Gecko/20100101 Firefox/103.0'

# Compile regex paterns for reducing whitespace in written files
white_reg = re.compile("\s{2,}")

# Compile regex paterns for removing hidden HTML elements
style_reg = re.compile("(display\s*:\s*(none|block);?|visibility\s*:\s*hidden;?)")
class_reg = re.compile('(hidden-sections?|dropdown|has-dropdown|sw-channel-dropdown|dropdown-toggle)')

## unn?
# Omit these pages
blacklist = ['cc.cnyric.org/districtpage.cfm?pageid=112', 'co.essex.ny.us/personnel', 'co.ontario.ny.us/94/human-resources', 'countyherkimer.digitaltowpath.org:10069/content/departments/view/9:field=services;/content/departmentservices/view/190', 'countyherkimer.digitaltowpath.org:10069/content/departments/view/9:field=services;/content/departmentservices/view/35', 'cs.monroecounty.gov/mccs/lists', 'herkimercounty.org/content/departments/view/9:field=services;/content/departmentservices/view/190', 'herkimercounty.org/content/departments/view/9:field=services;/content/departmentservices/view/35', 'jobs.albanyny.gov/default/jobs', 'monroecounty.gov/hr/lists', 'monroecounty.gov/mccs/lists', 'mycivilservice.rocklandgov.com/default/jobs', 'niagaracounty.com/employment/eligible-lists', 'ogdensburg.org/index.aspx?nid=345', 'penfield.org/multirss.php', 'tompkinscivilservice.org/civilservice/jobs', 'tompkinscivilservice.org/civilservice/jobs', 'swedishinstitute.edu/employment-at-swedish-institute', 'sunyacc.edu/job-listings']


# Auto blacklist
auto_blacklist_d = {}
auto_bl_path = '/home/joepers/code/jj_v' + version + '/auto_blacklist'
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
            print('\n Removing expired auto blacklist entry:', k, v)
            rem_l.append(k) 

    for i in rem_l:
        del auto_blacklist_d[i]

except Exception as errex:
    prant('cant open blacklist:', errex)



## application
# Exclude links that contain any of these. percent encodings must be lower case
bunkwords = ('academics', '5il.co', '5il%2eco', 'pnwboces.org', 'recruitfront.com', 'schoolapp.wnyric.org', 'professional development', 'career development', 'javascript:', '.pdf', '.jpg', '.ico', '.rtf', '.doc', '.mp4', '%2epdf', '%2ejpg', '%2eico', '%2ertf', '%2edoc', '%2emp4', 'mailto:', 'tel:', 'icon', 'description', 'specs', 'specification', 'guide', 'faq', 'images', 'exam scores', 'resume-sample', 'resume sample', 'directory', 'pupil personnel')

# Include links that include any of these
# Set high and low confidence jbw lists
jobwords_all_high = ('continuous recruitment', 'employment', 'job listing', 'job opening', 'job posting', 'job announcement', 'job opportunities', 'job vacancies', 'jobs available', 'available positions', 'open positions', 'available employment', 'career opportunities', 'employment opportunities', 'current vacancies', 'current job', 'current employment', 'current opening', 'current posting', 'current opportunities', 'careers at', 'jobs at', 'jobs @', 'work at', 'employment at', 'find your career', 'browse jobs', 'search jobs', 'vacancy postings', 'vacancy list', 'prospective employees', 'help wanted', 'work with', 'immediate opportunities', 'promotional announcements')
jobwords_all_low = ('join', 'job', 'job seeker', 'job title', 'positions', 'careers', 'human resource', 'personnel', 'vacancies', 'vacancy', 'posting', 'opening', 'recruitment')

jobwords_civ_high = ['upcoming exam', 'exam announcement', 'examination announcement', 'examinations list', 'civil service opportunities', 'civil service exam', 'civil service test', 'current civil service', 'open competitive', 'open-competitive'] 
jobwords_civ_high += jobwords_all_high

jobwords_civ_low = ['open to', 'civil service', 'exam', 'examination', 'test', 'current exam']
jobwords_civ_low += jobwords_all_low

jobwords_su_high = jobwords_all_high
jobwords_su_low = jobwords_all_low
jobwords_su_x_low = ('faculty', 'staff', 'adjunct', 'academic', 'support', 'instructional', 'administrative', 'professional', 'classified', 'coaching')






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
        self.domain = '://'.join(parse.urlparse(workingurl)[:2])  # Scheme and domain (with www). Used for building abspaths from rel links
        self.dup_domain = workingurl_dup.split('/')[0]  # Used for domain limiter

    # After successful request
    def add_html(self, html, vis_text, red_url, browser):
        self.html = html
        self.vis_text = vis_text.lower()
        self.red_url = red_url  
        self.browser = browser
        self.soup = BeautifulSoup(html, 'html5lib').find('body')
        prant('added html:', red_url)

    def __str__(self):
        return f'{self.org_name} {self.workingurl} {self.current_crawl_level} {self.parent_url} {self.jbw_type} {self.workingurl_dup} {self.req_attempt_num}'

    def clean_return(self):
        return self.org_name, self.workingurl, self.current_crawl_level, self.parent_url, self.jbw_type, self.workingurl_dup, self.req_attempt_num



    #def __iter__(self):
    #    return iter(self.__dict__.values())
    #    org_name, workingurl ... = list(working_o.r())[:5]


    # Add new working_o to the queue
    def add_to_queue(self):

        ## this doesnt work because html is added to working_o. too many items
        #org_name, workingurl, current_crawl_level, parent_url, jbw_type, url_dup, req_attempt_num = list(working_o)[:7]
        #org_name, workingurl, current_crawl_level, parent_url, jbw_type, workingurl_dup, req_attempt_num = working_o.clean_return()

        # Add new entry to CML
        s_checked_entry_f(self.workingurl_dup, None)

        # Create new working list: [org name, URL, crawl level, parent URL, jbw type, url_dup, req attempt]
        new_working_o = working_c(self.org_name, self.workingurl, self.current_crawl_level, self.parent_url, self.jbw_type, self.workingurl_dup, 0)
        prant('Putting list into queue:', new_working_o)
        prant('From:', self.parent_url)

        # Put new working list in queue
        try:
            #with q_lock:
            all_urls_q.put_nowait(new_working_o)
            working_c.total_count += 1
        except Exception as errex:
            prant('__Error trying to put into all_urls_q:', errex, new_working_o)


    # Mark errorlog portal url entry as successful fallback. ie: portal failed so now using homepage instead. don't count as portal error
    def fallback_success(self):
        if self.current_crawl_level < 0:
            try:
                prant('Homepage fallback success: Overwriting parent_url error:', self.parent_url)
                #with err_lock:
                error_urls_d[self.parent_url][-1].append('fallback_success')
            except KeyError:
                prant('__error parent url key not in error_urls_d', self.parent_url)
            except Exception as errex:
                prant('__error:', errex)


    # Detect redirects and check if the redirected page has already been processed
    def check_red(self):

        # Redirected
        if self.workingurl != self.red_url:
            red_url_dup = s_dup_checker_f(self.red_url)

            # Prevent trivial changes (eg: https upgrade) from being viewed as different urls
            if self.workingurl_dup != red_url_dup:
                prant('Redirect from/to:', self.workingurl, self.red_url)
                self.parent_url = self.workingurl
                self.workingurl = self.red_url
                self.workingurl_dup = red_url_dup

                # Update checked pages conf value to redirected
                conf_val = 'redirected'
                s_checked_entry_f(self.workingurl_dup, conf_val, self.browser)

                # Skip checked pages using redirected URL
                return proceed_f(self.red_url, red_url_dup)

        # Return True on all other results
        return True


    # Reduce excess whitespace with regex and check for minimum content
    def check_vis_text(self):

        self.vis_text = re.sub(white_reg, " ", self.vis_text)  

        # Skip if there is no useable visible text / soft 404s
        if len(self.vis_text) < empty_cutoff:

            # Mark error
            prant('jj_error 7: Empty vis text:', self.workingurl, len(self.vis_text))
            add_errorurls_f(self, 'jj_error 7', 'Empty vis text', False)

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


    # Save webpage vis text to file
    async def write_results(self):

        # Select jbw lists
        if self.jbw_type == 'civ':
            jobwords_high_conf = jobwords_civ_high
            jobwords_low_conf = jobwords_civ_low
        else:
            jobwords_high_conf = jobwords_su_high
            jobwords_low_conf = jobwords_su_low

        # Count jobwords on the page
        jbw_count = 0
        for i in jobwords_low_conf:
            if i in self.vis_text: jbw_count += 1
        for i in jobwords_high_conf:
            if i in self.vis_text: jbw_count += 2

        # Update outcome in checked_urls_d
        s_checked_entry_f(self.workingurl_dup, jbw_count, self.browser)

        ## combine this with fallback detection earlier?
        # Save results unless this a fallback homepage
        if self.current_crawl_level > -1:

            # Make jbw type dirs inside date dir
            dated_results_path = os.path.join(dater_path, 'results', self.jbw_type)
            if not os.path.exists(dated_results_path):
                os.makedirs(dated_results_path)

            # Make directory using org name
            org_path = os.path.join(dated_results_path, self.org_name)
            if not os.path.exists(org_path):
                os.makedirs(org_path)

            # Replace forward slashes so they aren't read as directory boundaries
            ## alternative: url_path = workingurl.replace('/', '%2F')
            url_path = parse.quote(self.workingurl, safe=':')
            html_path = os.path.join(org_path, url_path)

            # Combine jbw conf, browser, and vis text into a str. Separate by ascii delim char
            file_contents_s = str(jbw_count) + '\x1f' + self.browser + '\x1f' + self.vis_text

            # Write HTML to text file using url name (max length is 255)
            with open(html_path[:254], "w", encoding='ascii', errors='ignore') as write_html:
                write_html.write(file_contents_s)
            prant('Success: Write:', url_path)





# Print output to console and write to disk
def prant(*args):
    try:
        #print(os.getpid(), *args)
        print('', *args)
        out_t = '\n ' + str(datetime.now().strftime("%X "))
        with open(log_path, 'a', encoding='utf8', errors='ignore', buffering=819200) as log_file:
            log_file.write(out_t)
            for i in args:
                log_file.write(str(i))
                log_file.write(' ')
    except Exception as errex:
        print('__error prant', errex)



# Removes extra info from urls to prevent duplicate pages from being checked more than once
def s_dup_checker_f(url_dup):

    # Remove scheme
    if url_dup.startswith('http://') or url_dup.startswith('https://'): url_dup = url_dup.split('://')[1]
    else: print('__Error No scheme at:', url_dup)

    # Remove www. and variants. This also works with www3. and similar
    if url_dup.startswith('www'): url_dup = '.'.join(url_dup.split('.')[1:])

    url_dup = url_dup.split('#')[0] # Remove fragments
    url_dup = url_dup.replace('//', '/') # Remove double forward slashes outside of scheme
    url_dup = url_dup.strip(' \t\n\r/').lower() # Remove trailing whitespace and slash and then lowercase it

    return url_dup


# Only entrypoint into CML
def s_checked_entry_f(url_dup, *args):
    #with check_lock:
    checked_urls_d[url_dup] = args
    print('Updated outcome for/with:', url_dup, args)


# Return False if url has been requested already
def proceed_f(url, url_dup):

    # Exclude checked pages
    if url_dup in checked_urls_d:
        prant('Skipping:', url_dup)
        return False # Declare not to proceed


    '''
    # Count occurrences of domain in cml
    domain_count = 0

    ## switch to dup checker? +
    ## this domain strips scheme and www, which is different from domain elsewhere
    # Strip off scheme and www to form domain
    
    domain = new_url.split('/')[2]
    if domain.startswith('www'):
        domain = '.'.join(domain.split('.')[1:])
    
    # Count occurrences of domain in CML
    for cml_entry in checked_urls_d.keys():
        if domain in cml_entry: domain_count += 1
    #prant('Domain count:', domain_count, url_dup)

    # Exclude if domain occurrence limit is exceeded
    if domain_count > domain_limit:
        prant('Domain limit exceeded:', url_dup, domain_count)
        s_checked_entry_f(url_dup, 'Domain limit exceeded')
        return False
    '''


    domain = '://'.join(parse.urlparse(url)[:2]) 
    dup_domain = url_dup.split('/')[0]

    domain_o = domain_c.get_rp(domain, dup_domain)

    # Can fetch
    if domain_o.rp:
        if not domain_o.rp.can_fetch(user_agent_s, url):
            prant('can not fetch:', url)
            return False

        # Domain rate limiter
        time_elapsed = datetime.now().timestamp() - domain_o.last_req_ts
        crawl_delay = domain_o.rp.crawl_delay(user_agent_s)
        if time_elapsed < crawl_delay:
            prant('rp crawl delay wait:', url_dup, crawl_delay, time_elapsed)
            # put back in queue or wait
            import time
            time.sleep(crawl_delay - time_elapsed)

    # Exclude if domain occurrence limit is exceeded
    if domain_o.domain_count > domain_limit:
        prant('Domain limit exceeded:', url_dup, domain_o.domain_count)
        s_checked_entry_f(url_dup, 'Domain limit exceeded')
        return False


    # Exclude if the new_url is on the blacklist
    if url_dup in blacklist:
        prant('Blacklist invoked:', url_dup)
        s_checked_entry_f(url_dup, 'Blacklist invoked')
        return False

    # Declare to proceed
    return True




# Recursive child frame explorer
async def child_frame_f(frame, task_id):
    try:

        # Discard useless frames
        if frame.name == "about:srcdoc" or frame.name == "about:blank" or not frame.url or frame.url == "about:srcdoc" or frame.url == "about:blank" or frame.is_detached():
            return "", ""

        # Current frame content
        html = await frame.content()
        vis_text = await frame.inner_text('body')

        # Get child frame content
        #prant('num child frames:', len(frame.child_frames), frame, task_id)
        for c_f in frame.child_frames:
            ret_t = await child_frame_f(c_f, task_id)
            html += '\n' + ret_t[0]
            vis_text += '\n' + ret_t[1]
            prant('child frame appended:', frame.url, task_id)

        return html, vis_text

    except Exception as errex:
        prant('child_frame_f __error:', errex, task_id)
        return "", ""


# Decide which requester to use based on number of attmepts for that URL
async def looper_f(pw, session):
    task_id = asyncio.current_task().get_name()

    # End looper if all tasks report empty queue
    while not all(all_done_d.values()):

        # Get working list from queue
        try:
            async with q_lock:
                working_o = all_urls_q.get_nowait()
                all_done_d[task_id] = False

        # Empty queue
        except asyncio.QueueEmpty:
            prant('qqueue empty', task_id)
            all_done_d[task_id] = True
            await asyncio.sleep(8)
            continue

        except Exception as errex:
            prant('\n\n\n QUEUE __ERROR:', errex)
            await asyncio.sleep(8)
            continue
        
        # Choose requester based on attempt number
        try:
            working_o.req_attempt_num += 1  # Increment attempt num
            prant('got new working_list', working_o, task_id)

            if working_o.req_attempt_num < 3:
                print(111111111)
                await pw_req_f(working_o, task_id, pw)
            elif working_o.req_attempt_num < 5:
                await asyncio.wait_for(static_req_f(working_o, task_id, session), timeout=30)
            else:
                prant('All retries exhausted:', working_o.workingurl, working_o.req_attempt_num)
                working_c.prog_count += 1
                continue

        except asyncio.TimeoutError as errex:
            prant('looper timeout __error:', errex, task_id, working_o)
            add_errorurls_f(working_o, 'jj_error 8', 'looper timeout', True)
            continue

        except Exception as errex:
            prant('uncaught __error:', errex, task_id, sys.exc_info()[2].tb_lineno)
            add_errorurls_f(working_o, 'jj_error 9', errex, True)
            continue

        # Success
        if hasattr(working_o, 'html'):
            prant('has html:', working_o.workingurl)
            working_c.prog_count += 1
            prant('begin domain_o.update', working_o, task_id)
            domain_o.update(working_o.domain, working_o.dup_domain)  # Inc domain_count
            prant('begin fallback_success', working_o, task_id)
            working_o.fallback_success()  # Check and update fallback
            prant('begin check_red', working_o, task_id)
            if not working_o.check_red():  # Check if redirect URL has been processed already
                prant('check_red fail', working_o, task_id)
                continue
            prant('begin check_vis_text', working_o, task_id)
            if not working_o.check_vis_text():  # Check for minimum content/soft 404
                continue
            await working_o.write_results()  # Write result text to file
            crawler_f(working_o)  # Get more links from page

        #elif hassattr(working_o, erorr): handle errors here?
    
    # All tasks complete
    prant('Task complete:', task_id)


# Playwright requester
@timeout_decorator.timeout(20)
async def pw_req_f(working_o, task_id, pw):
    print(777777777777, task_id)
    # Select pw browser, context, and page
    stay = True
    while stay:

        for brow in brow_l:
            try:
                print(2222222, task_id, brow.is_connected())
                context = await brow.new_context(ignore_https_errors=True)
                context.set_default_timeout(20000)
                print('check closed1:', brow.is_connected(), context, task_id)
                page = await context.new_page()
                stay = False
                print(33333333333, task_id)
                #prant('using:', brow._impl_obj._browser_type.name, task_id)
                break

            # Remove browser from available list on error
            except Exception as errex:
                prant('__erroring', task_id)
                await clear_brows_f(pw, brow)

        # No browser available
        else:
            prant('__error brow list empty', task_id)
            await asyncio.sleep(4)

    # Check internet connectivity
    while pw_pause:
        prant('pw_pause invoked', task_id)
        await asyncio.sleep(4)

    # Request URL
    try:
        workingurl = working_o.workingurl
        prant('start pw req:', workingurl, task_id)
        print('check closed2:', brow.is_connected(), page.is_closed(), context, task_id)
        resp = await page.goto(workingurl)
        #await resp.finished()
        await page.wait_for_load_state('networkidle')
        prant('req timer:', resp.request.timing['responseEnd'], task_id)
        prant('end pw req:', workingurl, task_id)

        # Forbidden content types. only works with firefox
        if 'application/pdf' in resp.headers['content-type']:
            prant('jj_error 2: Forbidden content type:')
            add_errorurls_f(working_o, 'jj_error 2', 'Forbidden content type', False)
            return

        stat_code = resp.status
        stat_text = str(stat_code) + ' ' + str(resp.status_text)
        red_url = resp.url
        
        # Success
        if stat_code == 200:
            prant('suck it, splash&qt', workingurl, task_id)

            # Get child frame content recursively
            try:
                #prant('begin frame loop:', workingurl, len(page.frames), task_id)
                ret_t = await asyncio.wait_for(child_frame_f(page.main_frame, task_id), timeout=3)  # Prevent child frames from hanging forever
                html = '\n' + ret_t[0]
                vis_text = '\n' + ret_t[1]
                prant('end frame loop:', workingurl, task_id)

            # Fallback to html without child frame content
            except asyncio.TimeoutError:
                prant('child frame timeout', workingurl, task_id)
                html = await page.content()
                vis_text = await page.inner_text('body')
            ## redundant?
            except Exception as errex:
                prant('other child frame __error:', errex, workingurl, task_id)
                html = await page.content()
                vis_text = await page.inner_text('body')

            finally:
                working_o.add_html(html, vis_text, red_url, 'pw_browser')

        # Request errors
        # Don't retry
        elif stat_code == 404 or stat_code == 403:
            prant('jj_error 4:', workingurl, stat_text)
            add_errorurls_f(working_o, 'jj_error 4', stat_text, False)

        # Retry
        else:
            prant('jj_error 5: request error:', workingurl, stat_text)
            add_errorurls_f(working_o, 'jj_error 5', stat_text, True)
            if stat_code == 429:
                prant('__error 429', workingurl)
                await asyncio.sleep(4)

    # Timeout
    except TimeoutError:
        prant('jj_error 3: Timeout', workingurl)
        add_errorurls_f(working_o, 'jj_error 3', 'Timeout', True)

    # Error
    except Exception as errex:
        prant('jj_error 6: playwright error:', workingurl, errex, sys.exc_info()[2].tb_lineno)
        add_errorurls_f(working_o, 'jj_error 6', str(errex), True)

    # Close and return
    finally:
        try:
            await context.close()
        except Exception as errex:
            prant('cant close context:', errex)
        #return True  ## awaited coroutines must always return not None


# Static requester
async def static_req_f(working_o, task_id, session):

    workingurl = working_o.workingurl

    try:
        prant('start static req:', workingurl, task_id)
        async with session.get(workingurl, headers={'User-Agent': user_agent_s}, ssl=False) as resp:
            prant('end static req:', workingurl)

            # Must detect forbidden content types before getting html
            if 'application/pdf' in resp.headers['content-type']:
                prant('jj_error 2b: Forbidden content type:')
                add_errorurls_f(working_o, 'jj_error 2b', 'Forbidden content type (static)', False)
                return

            html = await resp.text()
            red_url = str(resp.url)
            stat_code = resp.status
            stat_text = str(stat_code) + ' ' + resp.reason

            # Success
            if stat_code == 200:
                prant('Static req success:', workingurl, stat_code)
                vis_text = vis_soup_f(html)  # Get vis soup

                working_o.add_html(html, vis_text, red_url, 'static_browser')

            # Don't retry
            elif stat_code == 404 or stat_code == 403:
                prant('jj_error 4b:', workingurl, stat_text)
                add_errorurls_f(working_o, 'jj_error 4b', stat_text, False)

            # Retry
            else:
                prant('jj_error 5b: request error:', workingurl, stat_text)
                add_errorurls_f(working_o, 'jj_error 5b',  stat_text, True)

    except asyncio.TimeoutError:
        prant('jj_error 3b: Timeout', workingurl)
        add_errorurls_f(working_o, 'jj_error 3b', 'Timeout', True)

    except Exception as errex:
        prant('jj_error 6b: Other Req', workingurl, errex)
        add_errorurls_f(working_o, 'jj_error 6b', str(errex), True)

    finally:
        return True



# url: [[org name, db type, crawl level], [[error number, error desc], [error number, error desc]], [final error flag, fallback flags]]
# Append URLs and info to the errorlog. Allows multiple errors (values) to each URL (key)
def add_errorurls_f(working_o, err_code, err_desc, back_in_q_b):
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
        except Exception as errex:
            prant('errorurls __error:', errex)

    # Add URL back to queue
    if back_in_q_b:
        prant('Putting back into queue:', workingurl)
        #with q_lock:
        all_urls_q.put_nowait(working_o)

    # Add final_error flag to errorlog
    else:
        final_error_f(working_o)

    ## should this be called only on final error or success?
    # Update checked pages value to error code
    s_checked_entry_f(workingurl_dup, err_code)
    return True


# Mark final errors in errorlog
def final_error_f(working_o):
    org_name, workingurl, current_crawl_level, parent_url, jbw_type, workingurl_dup, req_attempt_num = working_o.clean_return()
    try:
        working_c.prog_count += 1
        #with err_lock:
        error_urls_d[workingurl].append(['jj_final_error'])

        # If request failed on first URL (portal), use homepage as fallback
        if current_crawl_level == 0:
            prant('Using URL fallback:', parent_url)
            homepage_dup = s_dup_checker_f(parent_url)

            # Put homepage url into queue with -1 current crawl level
            if proceed_f(parent_url, homepage_dup):
                working_o.workingurl = parent_url
                working_o.current_crawl_level = -1
                working_o.parent_url = workingurl  ## parent of homepage fallback?
                working_o.workingurl_dup = homepage_dup
                working_o.add_to_queue()

    except Exception as errex:
        prant('final_e __error:', errex, workingurl)


# Separate the visible text from HTML
def vis_soup_f(html):

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





# Explore html to find more links and weigh confidence
def crawler_f(working_o):
    try:
        org_name, workingurl, current_crawl_level, parent_url, jbw_type, workingurl_dup, req_attempt_num = working_o.clean_return()
        domain = working_o.domain
        soup = working_o.soup

        # Remove non ascii characters, strip, percent encode
        #red_url = red_url.encode('ascii', 'ignore').decode().strip()
        #red_url = parse.quote(red_url, safe='/:')

        # Search for pagination class before checking crawl level
        for i in soup.find_all(class_='pagination'):
            prant('pagination class found:', workingurl)
            for ii in i.find_all('a'):  # Find anchor tags
                if ii.text.lower() == 'next':  # Find "next" page url

                    abspath = parse.urljoin(domain, ii.get('href')) # Get absolute url
                    url_dup = s_dup_checker_f(abspath) # Dup checker must be called prior to proceed_f

                    # Add to queue
                    if proceed_f(abspath, url_dup):
                        prant(workingurl, 'Adding pagination url:', abspath)
                        working_o.workingurl = abspath
                        working_o.workingurl_dup = url_dup
                        working_o.parent_url = workingurl
                        working_o.add_to_queue()

                ## look for next page button represented by angle bracket
                if '>' in ii.text: prant('pagination angle bracket', ii.text)


        # Limit crawl level
        if current_crawl_level > max_crawl_depth:
            return

        prant('Begin crawling:', workingurl)
        working_o.current_crawl_level += 1

        # Select job word list
        if working_o.jbw_type == 'civ':
            jobwords_high_conf = jobwords_civ_high
        else:
            jobwords_high_conf = jobwords_su_high

        # Separate soup into anchor tags
        fin_urls_l = []  # List of urls to add to queue
        for anchor_tag in soup.find_all('a'):

            # Replace newlines with a space. should this be after parent select?
            for br in anchor_tag.find_all("br"):
                br.replace_with(" ")

            # Build list of anchors and parent elements of single anchors. should this be recursive? ie grandparent
            if len(anchor_tag.parent.find_all('a')) == 1:
                tag = anchor_tag.parent
            else:
                tag = anchor_tag

            tag_content = str(tag.text).lower()


            # Skip if no jobwords in tag
            ## use this for only high conf jbws
            if not any(jbw in tag_content for jbw in jobwords_high_conf): continue

            '''
            ## use this for either low or high conf jbws, with new low conf format
            if not any(ttt in tag_content for ttt in jobwords_high_conf + jobwords_low_conf):
                if working_o.jbw_type == 'civ': continue
                # Exact match only for sch and uni extra low conf jbws
                else:
                    if not tag_content in jobwords_su_x_low: continue
            '''


            # Use lower tag for bunkwords search only. URL and text
            lower_tag = str(tag).lower()

            # Exclude if the tag contains a bunkword
            if any(yyy in lower_tag for yyy in bunkwords):
                prant('Bunk word detected:', workingurl, lower_tag[:99])
                continue


            '''
            # Jbw tally
            for i in jobwords_high_conf + jobwords_low_conf:
                if i in lower_tag:
                    async with lock: jbw_tally_ml.append(i)
            '''


            if tag.name == 'a': bs_url = tag.get('href') # Get url from anchor tag
            else: bs_url = tag.find('a').get('href') # Get url from first child anchor tag

            abspath = parse.urljoin(domain, bs_url).strip() # Convert relative paths to absolute and strip whitespace

            # Remove non printed characters, strip, and replace spaces
            #abspath = abspath.encode('ascii', 'ignore').decode().strip()
            #abspath = parse.quote(abspath)

            if abspath not in fin_urls_l:
                fin_urls_l.append(abspath)

        # Check new URLs and append to queue
        prant(len(fin_urls_l), 'links from', workingurl, fin_urls_l)
        for abspath in fin_urls_l:

            url_dup = s_dup_checker_f(abspath)

            # Add new link to queue
            if proceed_f(abspath, url_dup):
                working_o.workingurl = abspath
                working_o.workingurl_dup = url_dup
                working_o.parent_url = workingurl
                working_o.add_to_queue()


    except Exception as errex:
        prant('\njj_error 1: Crawler error detected. Skipping...', str(traceback.format_exc()), working_o)
        add_errorurls_f(working_o, 'jj_error 1', str(errex), True)
        return




# Restart pw browsers
async def clear_brows_f(pw, *args):
    prant('Begin clear_brows_f', args)

    # Manual restart
    for brow in args:
        async with brow_lock:
            brow_l.remove(brow)
        async with res_brow_lock:
            res_brow_set.add(brow)

    # Auto restart
    for brow in brow_l:
        if not brow.is_connected():
            prant('brow not connected', brow)
            async with brow_lock:
                brow_l.remove(brow)
            async with res_brow_lock:
                res_brow_set.add(brow)

    print('res_brow_set:', res_brow_set)
    # Restart nonworking pw browsers
    for brow in res_brow_set:
        brow_name = brow._impl_obj._browser_type.name

        # Wait for tasks to depopulate the browser before closing
        for i in range(20):
            if len(brow.contexts) > 0:
                print('cons still open open:', brow.contexts)
                await asyncio.sleep(1)
            else:
                prant('Closing brow:', brow)
                break
        else:
            prant('brow depop timeout', brow)

        # Close original browser
        await brow.close()

        # Start replacement browsers
        if brow_name == 'chromium':
            prant('starting chromium')
            new_browser = await pw.chromium.launch(args=['--disable-gpu'])
        elif brow_name == 'firefox':
            prant('starting firefox')
            new_browser = await pw.firefox.launch()
        else:
            prant('__error: cant detect browser name', brow, brow_name)
            continue

        prant('adding new brow:', new_browser)
        async with brow_lock:
            brow_l.append(new_browser)

    # Clear res_brow_set after iteration
    res_brow_set.clear()


# Bash ping to test internet connection
async def bash_ping_f():
    prant("Bash ping begin")

    proc = await asyncio.create_subprocess_shell(
            "timeout 3 ping -c 1 134.122.12.32",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

    if proc.returncode:
        prant('__error: bash ping fail:', proc.returncode)
    else:
        prant('bash ping success')

    return proc.returncode


# Restart internet connection
async def restart_nic_f():
    prant("Restart NIC begin")

    # Get NIC UUID
    proc = await asyncio.create_subprocess_shell(
            "nmcli --mode multiline connection show | awk '/UUID/ {print $2;}'",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)

    stdout, stderr = await proc.communicate()
    nic_uuid = stdout.decode()
    if proc.returncode:
        prant('__error: cant get NIC UUID', proc.returncode)
        return

    # Deactivate NIC
    proc = await asyncio.create_subprocess_shell(
            "nmcli con down " + nic_uuid,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        prant('__error: cant deactivate NIC', proc.returncode, nic_uuid)

    # Activate NIC
    proc = await asyncio.create_subprocess_shell(
            "nmcli con up " + nic_uuid,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        prant('__error: cant activate NIC UUID', proc.returncode, nic_uuid)
    else:
        prant('NIC restart success')


# Write shared objects to file to save progress
print('rec1', sys.getrecursionlimit())
sys.setrecursionlimit(50000)  # why did pickle.dump() start giving "maximum recursion depth exceeded while calling a Python object" ?
print('rec2', sys.getrecursionlimit())
async def save_objs_f():
    try:
        # Pickle queue of class objs
        async with q_lock:
            with open(queue_path, "wb") as f:
                pickle.dump(all_urls_q, f)

        # CML, errorlog, and multiorg
        for each_path, each_dict in (checked_path, checked_urls_d), (error_path, error_urls_d), (multi_org_d_path, multi_org_d):
            with open(each_path, "w") as f:
                json.dump(each_dict, f)
    except Exception as errex:
        prant('\n\n\nprog_f __ERROR:', errex, sys.exc_info()[2].tb_lineno)
    prant('prog save success')







async def main():
    prant('\n\n Program Start')

    # Start Playwright and aiohttp
    timeout = aiohttp.ClientTimeout(total=8)
    async with async_playwright() as pw, aiohttp.ClientSession(timeout=timeout) as session:
        pw_browser = await pw.chromium.launch(args=['--disable-gpu'])
        brow_l.append(pw_browser)

        pw_browser = await pw.firefox.launch()
        brow_l.append(pw_browser)


        # Start async scraper tasks
        for i in range(semaphore):
            task = asyncio.create_task(looper_f(pw, session))
            all_done_d[task.get_name()] = False



        # Wait for scraping to finish
        skip_tally = 0
        task_id = asyncio.current_task().get_name()
        while not all(all_done_d.values()):

            try:

                # Display progress
                prant('\nProgress:', working_c.prog_count, 'of', working_c.total_count)
                prant('mem use:', psutil.virtual_memory()[2])
                for t_brow in brow_l:
                    for t_con in t_brow.contexts:
                        prant(t_brow._impl_obj._browser_type.name, 'open pages:', len(t_con.pages), t_con.pages)
                print(6767676767)
                prant('running tasks:', len(asyncio.all_tasks()))
                #prant('running tasks:', asyncio.all_tasks())
                prant('len(brow_l):', len(brow_l))
                prant('len(res_brow_set):', len(res_brow_set))

                await asyncio.sleep(8)
                skip_tally += 1


                # Intermittent
                if skip_tally >= 2:
                    prant('begin prog save', task_id)
                    skip_tally = 0

                    # Save progress
                    await save_objs_f()


                    # Restart primary browser when mem usage is high
                    if psutil.virtual_memory()[2] > 50:
                        brow = brow_l[0]
                        prant('Memory usage too high. Restarting browser:', brow, task_id)
                        await clear_brows_f(pw, brow)

                    
                    # Check internet connectivity using pw on joesjorbs.com
                    ping_tally = 0
                    while True:
                        try:
                            prant('pw ping begin')
                            brow = brow_l[0]
                            context = await brow.new_context(ignore_https_errors=True)
                            page = await context.new_page()
                            page.set_default_timeout(3000)
                            resp = await page.goto('http://joesjorbs.com')
                            stat_code = resp.status
                            
                            # Success
                            if stat_code == 200:
                                pw_pause = False
                                prant('pw ping success')
                                break
                            else:
                                raise Exception('pw ping fail')

                        except Exception as errex:
                            prant('__error ping:', errex)
                            ping_tally += 1

                        finally:
                            try:
                                await context.close()
                            except Exception as errex:
                                prant('ping: could not close context', errex)


                        # Bash ping attempt
                        bash_ping_ret = bash_ping_f()

                        # Restart network interface on any two errors
                        if ping_tally > 1 or bash_ping_ret != 0:
                            pw_pause = True
                            await restart_nic_f()
                    

            except Exception as errex:
                prant('\n\n\nprog_f __ERROR:', errex, sys.exc_info()[2].tb_lineno)
                await asyncio.sleep(2)


        # All done. Close browsers
        for i in brow_l:
            await i.close()



        prant('\n\n\n\n =============================  Scrape complete  =============================')



















# Date dir to put results into
jorb_home = '/home/joepers/joes_jorbs'
#dater = datetime.now().strftime("%x").replace('/', '_')
dater = date.today().isoformat()
dater_path = os.path.join(jorb_home, dater)
if not os.path.exists(dater_path):
    os.makedirs(dater_path)

# Dir for error 7 files
err7_path = os.path.join(dater_path, 'jj_error_7')
if not os.path.exists(err7_path):
    os.makedirs(err7_path)

# Scraper options
max_crawl_depth = 1  # Webpage recursion depth
semaphore = 6  # Num of concurrent tasks
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
res_brow_set = set()
    

#jbw_tally_ml = [] # Used to determine the frequency that jbws are used (debugging)

# Set paths to files
queue_path = os.path.join(dater_path, 'queue')
log_path = os.path.join(dater_path, 'log_file')
checked_path = os.path.join(dater_path, 'checked_pages')
error_path = os.path.join(dater_path, 'errorlog')
multi_org_d_path = os.path.join(dater_path, 'multi_org_d')


# Nested dicts for multiple orgs covered by a URL 
multi_org_d = {}
multi_org_d['civ'] = {}
multi_org_d['sch'] = {}
multi_org_d['uni'] = {}



pw_pause = False  # Tell all tasks to wait if there is no internet connectivity
all_done_d = {}  # Each task states if the queue is empty






# Resume scraping using leftover results from the previously failed scraping attempt
try:

    # Read pickle queue of class objs
    with open(queue_path, "rb") as f:
        all_urls_q = pickle.load(f)

    # Read errorlog file as dict
    with open(error_path, "r") as f:
        error_urls_d = json.load(f)
    print('errorlog recovery complete')

    # Read CML file as dict
    with open(checked_path, "r") as f:
        checked_urls_d = json.load(f)
    print('CML recovery complete')

    # Read multi_org_d file as dict
    with open(multi_org_d_path, "r") as f:
        multi_org_d = json.load(f)
    print('multi_org_d recovery complete')

    working_c.total_count = all_urls_q.qsize()
    print('File queue success')


# Use original queue on any resumption error
except Exception as errex:
    print(errex, '\nUsing an original queue')

    checked_urls_d = {} # URLs that have been checked and their outcome (jbw conf, redirect, or error)
    error_urls_d = {} # URLs that have resulted in an error

    # Read DBs
    with open('/home/joepers/code/jj_v' + version + '/dbs/civ_db', 'r') as f:
        civ_db = json.load(f)
    with open('/home/joepers/code/jj_v' + version + '/dbs/sch_db', 'r') as f:
        sch_db = json.load(f)
    with open('/home/joepers/code/jj_v' + version + '/dbs/uni_db', 'r') as f:
        uni_db = json.load(f)

    
    # Testing purposes
    '''
    civ_db = [
    #["City of Albany", "https://jobs.albanyny.gov/jobopps", "http://www.albanyny.org"],
    #["City of Amsterdam", "https://www.amsterdamny.gov/Jobs.aspx", "http://www.amsterdamny.gov/"],
    #["City of fake", "https://jobs.albadfdggdgnyny.gov/jobopps", "http://www.albanyny.org"]
    ["Village of Fort Plain", "https://www.fortplain.org/contact-us/employment/", "https://www.fortplain.org/contact-us/employment/"]
    ]
    sch_db = []
    uni_db = []
    '''


    # Put all URLs into the queue
    all_urls_q = asyncio.Queue()
    for db, db_name in (civ_db, 'civ'), (sch_db, 'sch'), (uni_db, 'uni'):
        for org_name, em_url, homepage in db:

            # Skip if em URL is missing or marked
            if not em_url: continue
            if em_url.startswith('_'): continue

            url_dup = s_dup_checker_f(em_url)

            # URL as key, all org names using that URL as values
            try:
                multi_org_d[db_name][url_dup].append(org_name)  # Not first org using this URL
                print('Putting in multi org dict:', em_url)
            except:
                multi_org_d[db_name][url_dup] = [org_name]  # First org using this URL
                s_checked_entry_f(url_dup, None)

                # Put org name, em URL, initial crawl level, homepage, and jbws type into queue
                working_o = working_c(org_name, em_url, 0, homepage, db_name, url_dup, 0)
                all_urls_q.put_nowait(working_o)

        db = None  # Clear
        working_c.total_count = all_urls_q.qsize()




# robots.txt and domain tracker used for rate limiting
domain_lock = asyncio.Lock()
import ssl
ssl._create_default_https_context = ssl._create_unverified_context  ## rp.read req can throw error
class domain_c:
    domain_d = {}  # Used to store one robots.txt file per domin. [domain_dup]: obj
    def __init__(self, rp, dup_domain):
        self.rp = rp
        self.last_req_ts = 0.0
        self.domain_count = 0
        self.domain_d[dup_domain] = self  # dict of all objs

    # After req
    def update(domain, dup_domain):
        try:
            #with domain_lock:
            domain_c.domain_d[dup_domain].last_req_ts = datetime.now().timestamp()
            domain_c.domain_d[dup_domain].domain_count += 1
        except KeyError:  # This will be called on initial URLs because proceed_f is skipped
            prant('calling get_rp:', domain, dup_domain)
            domain_c.get_rp(domain, dup_domain)

    # Before req
    @timeout_decorator.timeout(8)
    def get_rp(domain, dup_domain):

        # Robot parser exists
        if dup_domain in domain_c.domain_d:
            return domain_c.domain_d[dup_domain]

        # Get robot parser
        else:
            try:
                prant('\nnew domain:', domain, dup_domain)
                rp = urllib.robotparser.RobotFileParser()
                rp.set_url(parse.urljoin(domain, "robots.txt"))
                rp.read()  # req
                prant(rp.url, 'rp read:', rp.can_fetch('*', '*'), rp.allow_all, rp.disallow_all)
                domain_c(rp, dup_domain)  # new obj with rp
                return domain_c.domain_d[dup_domain]
            except Exception as errex:
                prant('__error: rp read:', domain, errex)
                domain_c(None, dup_domain)  # new obj without rp
                return domain_c.domain_d[dup_domain]

            





# Start async event loop
asyncio.run(main(), debug=True)
#asyncio.run(main())





'''
# jbw tally
for i in jobwords_civ_low:
    r_count = jbw_tally_ml.count(i)
    print(i, '=', r_count)

for i in jobwords_su_low:
    r_count = jbw_tally_ml.count(i)
    print(i, '=', r_count)

for i in jobwords_civ_high:
    r_count = jbw_tally_ml.count(i)
    print(i, '=', r_count)

for i in jobwords_su_high:
    r_count = jbw_tally_ml.count(i)
    print(i, '=', r_count)
'''



# Convert CML to nice format that can be read by humans and json
## this prevents resumption because json converts None to null: NameError: name 'null' is not defined
cml_text = '{\n'
for k, v in checked_urls_d.items(): cml_text += json.dumps(k) + ': ' + json.dumps(v) + ',\n\n' # json uses double quotes
cml_text = cml_text[:-3] # Delete trailing newlines and comma
cml_text += '\n}'

# Write CML
with open(checked_path, 'w', encoding='utf8') as checked_file:
    checked_file.write(cml_text)



# url: [[org name, db type, crawl level], [[error number, error desc], [error number, error desc]], [final error flag, fallback flags]]
e_text = '{\n'
for k, v in error_urls_d.items(): e_text += json.dumps(k) + ': ' + json.dumps(v) + ',\n\n'
e_text = e_text[:-3]
e_text += '\n}'

with open(error_path, 'w', encoding='utf8') as error_file:
    error_file.write(e_text)



# Stop timer and display stats
duration = datetime.now() - startTime
print('\n\nPages checked =', len(checked_urls_d))
print('Duration =', round(duration.seconds / 60), 'minutes')
print('Pages/sec/tasks =', str((len(checked_urls_d) / duration.seconds) / semaphore)[:4], '\n')


'''
##
# Delete queue.txt to indicate program completed successfully
try:
    os.remove(queue_path)
    print('\nDeleted queue_path file\n')
except:
    print('\nFailed to delete queue_path file\n')
'''




dater_d = glob.glob(jorb_home + "/*") # List all date dirs
dater_d.sort(reverse=True)

# Select old and current results dirs
cur_dater_results_dir = os.path.join(dater_d[0], 'results')
count = 0
count1 = 0

# Allow one URL to cover multiple orgs
for db_type, url_d in multi_org_d.items():

    for url, org_names_l in url_d.items():

        # URL is used by more than one org
        if len(org_names_l) > 1:

            src_path = os.path.join(cur_dater_results_dir, db_type, org_names_l[0]) # Path to results of first org in list

            # Check if results exists for first org
            if os.path.isdir(src_path):
                print('Copying:', src_path)
                
                # Copy results from first org to all remaining orgs
                for dst_path in org_names_l[1:]:
                    dst_path = os.path.join(cur_dater_results_dir, db_type, dst_path)
                    print('to:', dst_path)
                    try: shutil.copytree(src_path, dst_path)
                    except Exception as errex: print(errex)
                    count += 1
                count1 += 1

            # this acts like a portal error for all other orgs in this list too. can also find these errors by finding multi_d orgs in the errorlog
            # Detect no results for first multi_d org
            else:
                print('\nmulti_org portal errors:', org_names_l)
print('\nMulti orgs:', count1)
print('Multi org files:', count)



# Fallback to older results if newer results are missing
# Skip this part if there are no old results
if len(dater_d) > 1:
    print('\nFalling back to old results ...')
    print(dater_d[1])
    old_dater_results_dir = os.path.join(dater_d[1], 'results')
    count = 0

    # Loop through each results dir
    for each_db in ['/civ', '/sch', '/uni']:

        # Select old and current db dirs
        cur_db_dir = cur_dater_results_dir + each_db + '/*'
        old_db_dir = old_dater_results_dir + each_db + '/*'
        inc_old_dir = cur_dater_results_dir + '/include_old' + each_db

        # Loop through each org name dir in the old db type dir
        for old_org_name_path in glob.glob(old_db_dir):

            # Remove path from org name
            old_org_name = str(old_org_name_path.split('/')[7:])[2:-2]

            # Check current db dir
            for cur_org_name_path in glob.glob(cur_db_dir):

                # Remove path from org name
                cur_org_name = str(cur_org_name_path.split('/')[7:])[2:-2]

                # Skip if the new dir has the result
                if old_org_name == cur_org_name:
                    break

            # If old org name dir is missing
            else:

                # Make old_include/old_org_name dir
                inc_org_name_path = inc_old_dir + '/' + old_org_name

                # Copy old org name dir to db type include_dir
                if not os.path.exists(inc_org_name_path):
                    shutil.copytree(old_org_name_path, inc_org_name_path)
                    count += 1
                    #print('Copied fallback result:', old_org_name)

                # Catch errors
                else:
                    print('Already exists:', inc_org_name_path)

print('Files in /include_old:', count)



# Copy results to remote server using bash
t = subprocess.run("/home/joepers/code/jj_v" + version + "/push_results.sh")




# Auto blacklist
# Get recurring error URLs and add them to existing dict
import err_parse

for url in err_parse.rec_errs_l:
    url_dup = s_dup_checker_f(url)
    auto_blacklist_d[url_dup] = today_dt.isoformat()

# Write file
with open(auto_bl_path, "w") as f:
    json.dump(auto_blacklist_d, f, indent=2)



















