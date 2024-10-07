# Description: Crawl and scrape the visible text from the webpages

# Version: 3.3


import asyncio
import json
import logging
import os
import pickle
import re
import shutil
import ssl
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from glob import glob
from urllib import parse, robotparser

import aiohttp
import enlighten
import playwright
import timeout_decorator
from bs4 import BeautifulSoup
from playwright.async_api import TimeoutError, async_playwright

import constants


startTime = datetime.now()


class Scrape:
    """
    The webpage object
    """

    all_done_d = {}  # Each task states if the queue is empty
    dynamic_db = {}
    prog_count = 0
    total_count = 0

    def __init__(
        self,
        org_name,
        workingurl,
        current_crawl_level,
        parent_url,
        jbw_type,
        workingurl_dup,
    ):
        self.org_name = org_name
        self.workingurl = workingurl
        self.current_crawl_level = current_crawl_level
        self.parent_url = parent_url
        self.jbw_type = jbw_type
        self.workingurl_dup = workingurl_dup
        self.req_attempt_num = 0
        self.domain = get_domain(workingurl)
        self.domain_dup = get_domain_dup(workingurl)  # Used for domain limiter

        # Select jbw list. Used for weighing confidence and finding links
        if self.jbw_type == "civ":
            self.jbws_high_conf = constants.JBWS_CIV_HIGH
            self.jbws_low_conf = constants.JBWS_CIV_LOW
        else:
            self.jbws_high_conf = constants.JBWS_SU_HIGH
            self.jbws_low_conf = constants.JBWS_SU_LOW

    def __str__(self):
        return f"""{self.org_name=} {self.workingurl=} {self.current_crawl_level=} {self.parent_url=} {self.jbw_type=} {self.workingurl_dup=} {self.req_attempt_num=} {self.domain=} {self.domain_dup=}"""
        # return f'{self.__dict__}'  # this returns huge html

    def clean_return(self):
        """
        Get important attributes. useful for adding new scrap to queue
        """
        return (
            self.org_name,
            self.workingurl,
            self.current_crawl_level,
            self.parent_url,
            self.jbw_type,
            self.workingurl_dup,
            self.req_attempt_num,
        )

    def add_to_queue(scrap):
        """
        Add new working list to the queue
        """
        logger.debug(
            f"Putting url into queue: {scrap.workingurl}. \nFrom: {scrap.parent_url}"
        )
        checked_urls_d_entry(scrap.workingurl_dup, None)  # Add new entry to CML

        try:
            Scrape.all_urls_q.put_nowait(scrap)
            Scrape.total_count += 1
        except Exception:
            logger.exception(f"__Error trying to put into all_urls_q: {scrap}")

    async def get_scrap(task_id):
        """
        Get a new url (working list) from the queue.
        Announce if the queue is empty and wait.
        An empty queue might get repopulated by other tasks.
        """
        try:
            scrap = Scrape.all_urls_q.get_nowait()
            Scrape.all_done_d[task_id] = False
            logger.debug(f"got new working_list {scrap}")
            return scrap

        except asyncio.QueueEmpty:
            logger.info(f"queue empty")
            Scrape.all_done_d[task_id] = True
            await asyncio.sleep(8)

        except Exception:
            logger.exception(f"QUEUE __ERROR:")
            await asyncio.sleep(8)

    def check_domain_rate_limiter(self):
        """
        Return True if page can be scrapped immediately.
        Put the url back in the queue and return False if you must wait.
        If the queue is small then just wait it out.
        """
        domain_tracker = get_robots_txt(self.workingurl, self.workingurl_dup)
        time_to_wait = domain_tracker.get_rate_limit_wait()
        if time_to_wait > 0:
            if (
                Scrape.all_urls_q.qsize() < 2 * constants.SEMAPHORE
            ):  # Prevent high frequency put and get loop
                logger.debug(
                    f"Small queue detected {Scrape.all_urls_q.qsize()=}. Waiting ..."
                )
                time.sleep(time_to_wait)
            else:
                logger.debug(f"Putting back into queue: {self.workingurl}")
                Scrape.all_urls_q.put_nowait(self)
                return False
        return True

    def choose_requester(self, task_id):
        """
        Choose the requester based on the number of attempts for that url
        """
        self.req_attempt_num += 1

        if self.req_attempt_num < 3:
            return PwReq(self)

        elif self.req_attempt_num < 5:
            return StaticReq(self)

        else:
            logger.info(
                f"All retries exhausted: {self.workingurl} {self.req_attempt_num}"
            )
            Scrape.prog_count += 1

    def fallback_success(self):
        """
        NEEDS UPDATING FOR DYNAMIC DB
        Mark errorlog entry as successful fallback. ie: the starting url failed so now using homepage instead. don't count as portal error
        """
        if self.current_crawl_level < 0:
            try:
                logger.info(
                    f"Homepage fallback success: Overwriting parent_url error: {self.parent_url}"
                )
                Scrape.error_urls_d[self.parent_url][-1].append("fallback_success")
            except KeyError:
                logger.exception(
                    f"__error parent url key not in Scrape.error_urls_d {self.parent_url}"
                )
            except Exception:
                logger.exception(f"__error:")

    def check_red(self):
        """
        Detect redirects and check if the redirected page has already been processed
        Return True to proceed
        """
        # Redirected
        if self.workingurl != self.red_url:
            red_url_dup = get_url_dup(self.red_url)

            # Prevent trivial changes (eg: https upgrade) from being viewed as different urls
            if self.workingurl_dup != red_url_dup:
                logger.debug(f"Redirect from/to: {self.workingurl} {self.red_url}")
                self.parent_url = self.workingurl
                self.workingurl = self.red_url
                self.workingurl_dup = red_url_dup

                # Update checked pages conf value to redirected
                conf_val = "redirected"
                checked_urls_d_entry(self.workingurl_dup, conf_val, self.browser)

                # Skip checked pages using redirected URL
                return allow_into_q(self.red_url)

        return True

    def homepage_fallback(self):
        """
        NEEDS UPDATING FOR DYNAMIC DB
        If request failed on first URL, use homepage as fallback
        """
        if self.current_crawl_level != 0:
            return

        if allow_into_q(self.parent_url):
            logger.info(f"Using URL fallback: {self.parent_url}")
            Scrape.prog_count -= 1  ## undo progress count from final error
            new_scrap = Scrape(
                org_name=self.org_name,
                workingurl=self.parent_url,
                current_crawl_level=-1,
                parent_url=self.workingurl,
                jbw_type=self.jbw_type,
                workingurl_dup=get_url_dup(self.parent_url),
            )
            Scrape.add_to_queue(new_scrap)

    def get_pagination(self):
        """
        Always include pagination links.
        """
        for pag_class in self.soup.find_all(class_="pagination"):
            logger.info(f"pagination class found: {self.workingurl}")
            for anchor_tag in pag_class.find_all("a"):  # Find anchor tags
                logger.info(f"anchor_tag.text {anchor_tag.text}")
                if "next" in anchor_tag.text.lower():  # Find "next" page url
                    # Add to queue
                    abspath = parse.urljoin(self.domain, anchor_tag.get("href"))
                    if allow_into_q(abspath):
                        logger.info(
                            f"Adding pagination url: {abspath} {self.workingurl}"
                        )
                        new_scrap = Scrape(
                            org_name=self.org_name,
                            workingurl=abspath,
                            current_crawl_level=self.current_crawl_level,  ##
                            parent_url=self.workingurl,
                            jbw_type=self.jbw_type,
                            workingurl_dup=get_url_dup(abspath),
                        )
                        Scrape.add_to_queue(new_scrap)

                # look for next page button represented by angle bracket
                elif ">" in anchor_tag.text:
                    logger.debug(f"pagination angle bracket {anchor_tag.text}")

    def get_links(self):
        """
        Return a set of all the urls found on the page that likely contain job postings.
        """
        new_urls = set()
        for anchor_tag in self.soup.find_all("a"):
            # Widen search of jbws if only 1 url in elem. should this be recursive? ie grandparent
            if len(anchor_tag.parent.find_all("a")) == 1:
                tag = anchor_tag.parent
            else:
                tag = anchor_tag

            # Newlines will mess up jbw and bunk detection
            for br in tag.find_all("br"):
                br.replace_with(" ")

            # Skip if the tag contains a bunkword
            if any(bunkword in str(tag).lower() for bunkword in constants.BUNKWORDS):
                # logger.debug(f'Bunk word detected: {self.workingurl} {str(tag)[:99]}')
                continue

            # Skip if no jobwords in content
            ## use this for only high conf jbws
            tag_content = str(tag.text).lower().strip()
            if not any(jbw in tag_content for jbw in self.jbws_high_conf):
                # logger.debug(f'No jobwords detected: {workingurl} {tag_content[:99]}')
                continue

            """
            ## use this for either low or high conf jbws, with new low conf format
            if not any(ttt in tag_content for ttt in jbws_high_conf + jbws_low_conf):
                if self.jbw_type == 'civ': continue
                # Exact match only for sch and uni extra low conf jbws
                else:
                    if not tag_content in jbws_su_x_low: continue
            """

            bs_url = anchor_tag.get("href")
            abspath = parse.urljoin(
                self.domain, bs_url
            ).strip()  # Convert relative paths to absolute and strip whitespace
            logger.debug(f"tag_content: {abspath} {tag_content}")
            # Remove non printed characters
            # abspath = abspath.encode('ascii', 'ignore').decode()
            # abspath = parse.quote(abspath)

            new_urls.add(abspath)

        logger.info(f"Found {len(new_urls)} new links from {self.workingurl}")
        return new_urls

    def crawler(self):
        """
        Explore html to find more links and weigh confidence
        """
        try:
            self.get_pagination()  # Search for pagination links before checking crawl level

            # Limit crawl level
            if self.current_crawl_level > constants.MAX_CRAWL_DEPTH:
                return

            logger.debug(f"Begin crawling: {self.workingurl}")
            self.current_crawl_level += 1

            # Check new URLs and append to queue
            for abspath in self.get_links():
                if allow_into_q(abspath):
                    new_scrap = Scrape(
                        org_name=self.org_name,
                        workingurl=abspath,
                        current_crawl_level=self.current_crawl_level,
                        parent_url=self.workingurl,
                        jbw_type=self.jbw_type,
                        workingurl_dup=get_url_dup(abspath),
                    )
                    Scrape.add_to_queue(new_scrap)

        except Exception as errex:
            logger.exception(
                f"\njj_error 1: Crawler error detected. Skipping... {self}"
            )
            add_errorurls(self, "jj_error 1", str(errex), True)

    def count_jbws(self):
        """
        Determine the confidence that a page has job postings
        """
        self.jbw_count = 0
        for i in self.jbws_low_conf:
            if i in self.vis_text:
                self.jbw_count += 1
        for i in self.jbws_high_conf:
            if i in self.vis_text:
                self.jbw_count += 2

    def update_dynamic_db(self):
        """
        Append the url and the job confidence to the dynamic employment url database.
        """
        if not self.org_name in Scrape.dynamic_db:
            Scrape.dynamic_db[self.org_name] = []

        Scrape.dynamic_db[self.org_name].append([self.workingurl, self.jbw_count])

    def write_results(self):
        """
        Save the webpage visible text to a file
        """
        # Dont save results if this a fallback homepage
        if self.current_crawl_level < 0:
            return

        # Make dir
        org_path = os.path.join(constants.RESULTS_PATH, self.jbw_type, self.org_name)
        if not os.path.exists(org_path):
            os.makedirs(org_path)

        # Make filename
        url_path = parse.quote(
            self.workingurl, safe=":"
        )  # Replace forward slashes so they aren't read as directory boundaries
        html_path = os.path.join(org_path, url_path)[:254]  # max length is 255 chars

        # Make file content. Separate with ascii delim char
        file_contents_s = f"{self.jbw_count} \x1f {self.vis_text}"

        # Write text to file
        with open(html_path, "w", encoding="ascii", errors="ignore") as write_html:
            write_html.write(file_contents_s)
        logger.info(f"Success: Write: {url_path}")


class RequesterBase:
    """
    URL requesting super class
    """

    req_pause = False  # Tell all tasks to wait if there is no internet connectivity

    def __init__(self, scrap):
        self.url = scrap.workingurl

    def check_content_type(self, scrap):
        """
        Exclude forbidden content types. ex: pdf
        """
        content_type = self.resp.headers["content-type"]
        if "text/html" in content_type:
            return True
        else:
            logger.info(
                f"jj_error 2{self.ec_char}: Forbidden content type: {content_type} {self.url}"
            )
            add_errorurls(
                scrap, f"jj_error 2{self.ec_char}", "Forbidden content type", False
            )
            return False

    def reduce_vis_text(self):
        """
        Remove excess whitespace with regex
        """
        self.vis_text = re.sub(constants.WHITE_REG, " ", self.vis_text)
        self.vis_text = self.vis_text.replace(
            "\x1f", ""
        )  # Remove delim char for webserver
        self.vis_text = self.vis_text.lower()

    def check_vis_text(self, scrap):
        """
        Check for a minimum amount of content. ie: soft 404
        """
        # logger.debug(f'begin check_vis_text {self.url}')
        self.reduce_vis_text()

        if len(self.vis_text) > constants.EMPTY_CUTOFF:
            return True
        else:
            logger.warning(
                f"jj_error 7{self.ec_char}: Empty vis text: {self.url} {len(self.vis_text)}"
            )
            add_errorurls(scrap, f"jj_error 7{self.ec_char}", "Empty vis text", False)

            # Debug err7 by saving to separate dir
            url_path = parse.quote(self.url, safe=":")
            html_path = os.path.join(constants.ERR7_PATH, url_path)
            with open(
                html_path[:254], "w", encoding="ascii", errors="ignore"
            ) as write_html:
                write_html.write(self.vis_text)

            return False  # Dont retry

    def add_html(self, scrap):
        """
        Copy response data to scrap object
        """
        scrap.html = self.html
        scrap.vis_text = self.vis_text
        scrap.red_url = str(self.resp.url)  # aiohttp returns yarl obj not str
        scrap.browser = self.name
        scrap.soup = BeautifulSoup(self.html, "html5lib").find("body")
        logger.debug(f"added html: {self.url}")

    def inc_crawl_delay_429(self, scrap):
        """
        The server has a returned http error 429: Too Many Requests.
        Double the time for the rate limiter.
        If a rate limit doesn't exist, then create one.
        """
        logger.warning(f"err code 429 {self.url}")
        crawl_delay = BotExcluder.domain_d[scrap.domain_dup].dynamic_crawl_delay
        logger.warning(f"Current crawl delay: {crawl_delay}")

        if (
            not crawl_delay
            or not isinstance(crawl_delay, (int, float))
            or crawl_delay < 2
        ):
            BotExcluder.domain_d[scrap.domain_dup].dynamic_crawl_delay = 2
        else:
            BotExcluder.domain_d[scrap.domain_dup].dynamic_crawl_delay *= 2
        logger.warning(
            f"New crawl delay: {BotExcluder.domain_d[scrap.domain_dup].dynamic_crawl_delay}"
        )

    def resp_err_handler(self, scrap):
        """
        Determine if the url should be tried again based on the http status code.
        """

        # Don't retry req
        if self.resp.status in constants.NO_RETRY_HTTP_ERROR_CODES:
            logger.warning(f"jj_error 4{self.ec_char}: {self.url} {self.status_text}")
            add_errorurls(scrap, f"jj_error 4{self.ec_char}", self.status_text, False)

        # Retry req
        else:
            if self.resp.status == 429:
                self.inc_crawl_delay_429(scrap)

            logger.warning(
                f"jj_error 5{self.ec_char}: request error: {self.url} {self.status_text}"
            )
            add_errorurls(scrap, f"jj_error 5{self.ec_char}", self.status_text, True)

    def failed_req_handler(self, scrap, errex):
        """
        Habndle errors that are not based on the http status code.
        """
        if isinstance(errex, asyncio.TimeoutError) or isinstance(errex, TimeoutError):
            logger.warning(f"jj_error 3{self.ec_char}: Timeout {self.url}")
            add_errorurls(scrap, f"jj_error 3{self.ec_char}", "Timeout", True)

        else:
            logger.warning(
                f"jj_error 6{self.ec_char}: Requester error: {errex} {self.url} {sys.exc_info()[2].tb_lineno}"
            )
            add_errorurls(scrap, f"jj_error 6{self.ec_char}", str(errex), True)


class PwReq(RequesterBase):
    """
    The Playwright requester subclass.
    This is the primary means of requesting a url.
    """

    def __init__(self, scrap):
        self.name = "pw"
        self.ec_char = "a"
        super().__init__(scrap)

    async def get_page(self):
        """
        Create the playwright browser context and new page
        """
        self.context = await PwReq.brow.new_context(
            ignore_https_errors=True
        )  ## slow execution here?
        self.page = await self.context.new_page()
        self.page.set_default_navigation_timeout(constants.pw_req_timeout)
        # logger.debug(f'using brow: {PwReq.brow._impl_obj._browser_type.name}')

    async def request_url(self):
        """
        Get the http response and status code
        """
        logger.info(f"begin req pw {self.url}")
        await self.get_page()
        self.resp = await self.page.goto(self.url)
        await self.page.wait_for_load_state("networkidle")
        self.status_text = f"{self.resp.status} {self.resp.status_text}"
        logger.info(f"end req pw {self.url}")

    async def get_content(self):
        """
        Get the page content, including all iframes content
        """
        # logger.debug(f'begin frame loop: {self.url} {len(self.page.frames)}')
        # Main frame and child frame content
        try:
            self.html, self.vis_text = await asyncio.wait_for(
                self.get_iframes_content(self.page.main_frame),
                timeout=constants.iframe_timeout,
            )
            # logger.debug(f'end frame loop: {self.url}')

        # Fallback to no child frame content
        except Exception as errex:
            logger.warning(
                f"child frame error: {repr(errex)} {self.url}"
            )  # repr needed because TimeoutError has no message
            self.html = await self.page.content()
            self.vis_text = await self.page.inner_text("body")

    async def get_iframes_content(self, frame):
        """
        Recursive child frame explorer
        """
        try:
            # Discard useless frames
            if (
                frame.name == "about:srcdoc"
                or frame.name == "about:blank"
                or not frame.url
                or frame.url == "about:srcdoc"
                or frame.url == "about:blank"
                or frame.is_detached()
            ):
                return "", ""

            # Current frame content
            html = await frame.content()
            vis_text = await frame.inner_text("body")

            # Append recursive child frame content
            logger.debug(f"num child frames: {len(frame.child_frames)} {frame}")
            for child_frame in frame.child_frames:
                ret_t = await self.get_iframes_content(child_frame)
                html += ret_t[0]  ## cant do augmented assignment on multiple targets
                vis_text += ret_t[1]
                # logger.debug(f'child frame appended: {frame.url}')

            return f"\n{html}", f"\n{vis_text}"

        except Exception as errex:
            logger.warning(f"get_iframes_content_f __error: {errex}")
            return "", ""

    async def close_page(self):
        try:
            await self.context.close()
        except Exception:
            logger.exception(f"cant close pw context")

    async def close_session():
        await PwReq.session.stop()


class PwPingReq(PwReq):
    """
    A subclass of the Playwright requester used only for testing the internet connection with ping
    """

    def __init__(self):
        scrap = Scrape(
            "ping_test",
            "http://joesjorbs.com",
            0,
            "http://joesjorbs.com",
            "ping_test",
            "joesjorbs.com",
        )
        super().__init__(scrap)


class StaticReq(RequesterBase):
    """
    The aiohttp requester subclass.
    This is the backup means of requesting a url.
    """

    def __init__(self, scrap):
        self.name = "static"
        self.ec_char = "b"
        super().__init__(scrap)

    async def request_url(self):
        """
        Get the http response and status code
        """
        logger.info(f"begin req static {self.url}")
        self.resp = await StaticReq.session.get(
            self.url, headers={"User-Agent": constants.USER_AGENT_S}, ssl=False
        )
        self.status_text = f"{self.resp.status} {self.resp.reason}"
        logger.info(f"end req static {self.url}")

    async def get_content(self):
        """
        Get the page content, including all iframes content
        """
        self.html = await self.resp.text()
        self.vis_text = self.get_vis_text()

    def get_vis_text(self):
        """
        Remove nonvisible html elements
        """
        vis_soup = BeautifulSoup(self.html, "html5lib").find("body")
        for x in vis_soup(
            ["script", "style"]
        ):  # Remove script, style, and empty elements
            x.decompose()
        for x in vis_soup.find_all(
            "", {"style": constants.STYLE_REG}
        ):  # Remove all of the hidden style attributes  ## unn?
            x.decompose()
        for x in vis_soup.find_all("", {"type": "hidden"}):  # Type="hidden" attribute
            x.decompose()
        for x in vis_soup(
            class_=constants.CLASS_REG
        ):  # Hidden section(s) and dropdown classes
            x.decompose()
        return vis_soup.text

    async def close_page(self):
        if not hasattr(self, "resp"):
            logger.warning(f"static response does not exist")
        else:
            try:
                self.resp.close()
            except Exception:
                logger.exception(f"cant close static response")

    async def close_session():
        await StaticReq.session.close()


def get_url_dup(url):
    """
    Remove insignificant info from the url.
    Ex: www, fragments, and trailing slashes
    """
    url_dup = url.split("://")[1].split("#")[0]  # Remove scheme and fragments

    # Remove www subdomains. This works with variants like www3.
    if url_dup.startswith("www"):
        url_dup = url_dup.split(".", maxsplit=1)[1]

    url_dup = url_dup.replace(
        "//", "/"
    )  # Remove double forward slashes outside of scheme
    url_dup = url_dup.strip(" \t\n\r/")  # Remove trailing whitespace and slash

    return url_dup.lower()


def get_domain(url):
    """
    Includes scheme and www.
    """
    return "://".join(parse.urlparse(url)[:2])


def get_domain_dup(url):
    """
    Excludes scheme and www.
    """
    url_dup = get_url_dup(url)
    return url_dup.split("/")[0]


def checked_urls_d_entry(url_dup, *args):
    """
    Maintain a dict of all the urls that have been checked
    """
    Scrape.checked_urls_d[url_dup] = args
    logger.debug(f"Updated outcome for/with: {url_dup} {args}")


def get_robots_txt(url, url_dup):
    """
    Get the robot parser info for that domain
    """
    domain_dup = get_domain_dup(url)
    if domain_dup in BotExcluder.domain_d:  # Use cached robots.txt
        return BotExcluder.domain_d[domain_dup]
    else:
        return BotExcluder(url, domain_dup)  # Request robots.txt


def allow_into_q(url) -> bool:
    """
    Determine if the url should be put in the queue
    Return True to proceed
    """
    # No scheme
    if not url.startswith("http://") and not url.startswith("https://"):
        logger.warning(f"__Error No scheme at: {url}")
        return False

    url_dup = get_url_dup(url)

    # Exclude checked pages
    if url_dup in Scrape.checked_urls_d:
        logger.debug(f"Skipping: {url_dup}")
        return False

    # Check robots.txt
    domain_tracker = get_robots_txt(url, url_dup)
    if not domain_tracker.can_request(url):
        logger.debug(f"request disallowed: {url_dup}")
        return False

    # Exclude if the new_url is on the blacklist
    if url_dup in Blacklist.combined_l:
        logger.info(f"Blacklist invoked: {url_dup}")
        checked_urls_d_entry(url_dup, "Blacklist invoked")
        return False

    return True


async def check_internet_connection():
    """
    Check if a pause has been announced for all requests.
    The pause will be lifted when a ping succeeds
    """
    while RequesterBase.req_pause:
        logger.warning(f"req_pause invoked")
        await asyncio.sleep(4)


async def req_looper():
    """
    The request loop.
    Get a url from the queue and process it.
    Repeat until all tasks agree that the queue is empty.
    """
    task_id = asyncio.current_task().get_name()
    logger.info(f"Task begin")

    # End looper when all tasks report empty queue
    while not all(Scrape.all_done_d.values()):
        await check_internet_connection()

        scrap = await Scrape.get_scrap(task_id)  # Get url from queue
        if not scrap or not scrap.check_domain_rate_limiter():
            continue

        requester = scrap.choose_requester(task_id)
        if not requester:
            continue

        try:
            await requester.request_url()

            if requester.resp.status == 200:
                if not requester.check_content_type(scrap):
                    continue
                await requester.get_content()
                if not requester.check_vis_text(scrap):
                    continue
                requester.add_html(scrap)
                req_success(scrap)
            else:
                requester.resp_err_handler(scrap)

        except asyncio.TimeoutError as errex:
            logger.warning(f"looper timeout __error: {repr(errex)} {scrap.workingurl}")
            add_errorurls(scrap, "jj_error 8", "looper timeout", True)

        except Exception as errex:
            requester.failed_req_handler(scrap, errex)
        finally:
            await requester.close_page()

    logger.info(f"Task complete: {task_id}")


def req_success(scrap):
    """
    Process a successful webpage retrieval.
    Write the page content and crawl for more links
    """
    Scrape.prog_count += 1

    # logger.debug(f'begin robots.txt update {scrap} {BotExcluder.domain_d[scrap.domain_dup]}')
    BotExcluder.domain_d[scrap.domain_dup].update()  # Inc domain_count

    # logger.debug(f'begin fallback_success {scrap}')
    scrap.fallback_success()  # Check and update fallback

    scrap.count_jbws()

    scrap.update_dynamic_db()

    checked_urls_d_entry(scrap.workingurl_dup, scrap.jbw_count, scrap.browser)

    # logger.debug(f'begin check_red {scrap}')
    if not scrap.check_red():  # Check if redirect URL has been processed already
        return

    scrap.write_results()  # Write result text to file
    scrap.crawler()  # Get more links from page


def add_errorurls(scrap, err_code, err_desc, back_in_q_b):
    """
    Append URLs and info to the errorlog. Allows multiple errors (values) to each URL (key)
    url: [[org name, db type, crawl level], [[error number, error desc], [error number, error desc]], [final error flag, fallback flags]]
    """
    (
        org_name,
        workingurl,
        current_crawl_level,
        parent_url,
        jbw_type,
        workingurl_dup,
        req_attempt_num,
    ) = scrap.clean_return()

    ## errorlog splits should use non printable char
    # Remove commas from text to prevent splitting errors when reading errorlog
    # err_desc = err_desc.replace(',', '').strip()  ## unn

    # First error for this url
    if not workingurl in Scrape.error_urls_d:
        Scrape.error_urls_d[workingurl] = [
            [org_name, jbw_type, current_crawl_level],
            [[err_desc, err_code]],
        ]

    # Not the first error for this url
    else:
        try:
            Scrape.error_urls_d[workingurl][1].append([err_desc, err_code])
        except Exception:
            logger.exception(f"Cant append error to errorlog: {workingurl}")

    # Add URL back to queue
    if back_in_q_b:
        logger.debug(f"Putting back into queue: {workingurl}")
        Scrape.all_urls_q.put_nowait(scrap)

    # Add final_error flag to errorlog
    else:
        final_error(scrap)

    ## should this be called only on final error or success?
    # Update checked pages value to error code
    checked_urls_d_entry(workingurl_dup, err_code)


def final_error(scrap):
    """
    Mark final errors in the errorlog.
    This designates the url did not proceed past this error
    """
    try:
        Scrape.prog_count += 1
        Scrape.error_urls_d[scrap.workingurl].append(["jj_final_error"])
        scrap.homepage_fallback()
    except Exception:
        logger.exception(
            f"final_e __error: {scrap.workingurl} {sys.exc_info()[2].tb_lineno}"
        )


async def create_req_sessions():
    """
    Initialize the Playwright and aiohttp instances
    """
    PwReq.session = await async_playwright().start()
    PwReq.brow = await PwReq.session.chromium.launch(args=["--disable-gpu"])

    timeout = aiohttp.ClientTimeout(total=constants.static_timeout)
    StaticReq.session = aiohttp.ClientSession(timeout=timeout)


async def pw_ping():
    """
    Ping joesjorbs.com using playwright
    On success: Return True and announce that requesting can continue
    """
    logger.debug(f"pw ping begin")
    try:
        ping_requester = PwPingReq()
        await ping_requester.request_url()

        if ping_requester.resp.status == 200:
            RequesterBase.req_pause = False
            logger.debug(f"pw ping success")
            return True
        else:
            raise Exception("pw ping error: {ping_requester.resp.status}")

    except playwright._impl._errors.TimeoutError as errex:
        logger.warning(f"jj_error 3c: Ping timeout")
        add_errorurls(scrap, f"jj_error 3c", "Timeout", True)

    except Exception:
        logger.exception(f"__error ping:")

    finally:
        await ping_requester.close_page()


async def ping_test():
    """
    Check internet connectivity.
    If playwright ping fails, then check with bash ping.
    If playwright fails multiple times or if bash ping fails, then restart the NIC
    """
    ping_tally = 0
    while True:
        if await pw_ping():
            return

        ping_tally += 1
        bash_ping_ret = await bash_ping()

        ## should restart pw not nic if bash succeeds but pw fails
        # Restart network interface on any two errors
        if ping_tally > 1 or bash_ping_ret != 0:
            logger.debug(f"check these {ping_tally} {bash_ping_ret}")
            RequesterBase.req_pause = True
            await restart_nic()


async def bash_ping():
    """
    Bash ping to test internet connection on joesjorbs ip address
    Return the exit code.
    """
    logger.info(f'{"Bash ping begin"}')

    proc = await asyncio.create_subprocess_shell(
        f"timeout {constants.ping_timeout} ping -c 1 134.122.12.32",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode:
        logger.critical(f"bash ping fail: {proc.returncode}")
    else:
        logger.info(f"bash ping success")

    return proc.returncode


async def restart_nic():
    """
    Restart the internet connection in bash
    """
    logger.info(f'{"Restart NIC begin"}')

    # Get NIC UUID
    proc = await asyncio.create_subprocess_shell(
        "nmcli connection show | grep ethernet | awk '{print $4;}'",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    nic_uuid = stdout.decode()
    if proc.returncode:
        logger.critical(f"cant get NIC UUID {proc.returncode}")
        return

    # Deactivate NIC
    proc = await asyncio.create_subprocess_shell(
        "nmcli con down " + nic_uuid,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        logger.critical(f"cant deactivate NIC {proc.returncode} {nic_uuid}")

    # Activate NIC
    proc = await asyncio.create_subprocess_shell(
        "nmcli con up " + nic_uuid,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode:
        logger.critical(f"cant activate NIC {proc.returncode} {nic_uuid}")
    else:
        logger.info(f"NIC start success")


def save_progress():
    """
    Write objects necessary for resumption to files
    """
    logger.debug(f"begin prog save")
    try:
        # Pickle queue of scraps
        with open(constants.QUEUE_PATH, "wb") as f:
            pickle.dump(Scrape.all_urls_q, f)

        # CML, errorlog, and multiorg
        for each_path, each_dict in (
            (constants.CHECKED_PATH, Scrape.checked_urls_d),
            (constants.ERROR_PATH, Scrape.error_urls_d),
            (constants.MULTI_ORG_D_PATH, Scrape.multi_org_d),
        ):
            with open(each_path, "w") as f:
                json.dump(each_dict, f)

        logger.info(f"progress save success")

    except Exception:
        logger.exception(f"\n prog_f __ERROR: {sys.exc_info()[2].tb_lineno}")


def create_progress_bar():
    manager = enlighten.get_manager()
    return manager.counter(total=1000, leave=False)


def update_progress_bar(progress_bar):
    # logger.info(f'\nProgress: {Scrape.prog_count} of {Scrape.total_count}')
    # logger.info(f'Browser{PwReq.brow._impl_obj._browser_type.name}')
    # logger.info(f'running tasks: {len(asyncio.all_tasks())}')
    # prant('running tasks:', asyncio.all_tasks())
    progress_bar.count = Scrape.prog_count
    progress_bar.total = Scrape.total_count
    progress_bar.refresh()


async def run_scraper():
    """
    Start each async task in the url request loop
    """
    logger.info(f"{constants.SEMAPHORE=}")
    for i in range(constants.SEMAPHORE):
        task = asyncio.create_task(req_looper())
        Scrape.all_done_d[task.get_name()] = False


async def maintenance(progress_bar):
    """
    Run housekeeping functions periodically
    """
    await asyncio.sleep(10)
    try:
        await ping_test()
        save_progress()
        update_progress_bar(progress_bar)
    except Exception:
        logger.exception(f"\nmaintenance __ERROR: {sys.exc_info()[2].tb_lineno}")


async def main():
    """
    Start the webscraper and perform maintenance while you wait
    """
    await create_req_sessions()
    await run_scraper()
    progress_bar = create_progress_bar()

    # Wait for scraping to finish
    while not all(Scrape.all_done_d.values()):
        await maintenance(progress_bar)

    logger.info(f"  Scrape complete  ".center(70, "="))
    await cleanup()


async def cleanup():
    """
    Close the browser sessions
    """
    try:
        await PwReq.brow.close()
    except Exception:
        logger.exception(f"\ncant close pw brow")

    for req_class in RequesterBase.__subclasses__():
        try:
            await req_class.close_session()
        except Exception:
            logger.exception(f"\ncant close session: {req_class.__name__}")


class BotExcluder:
    """
    This scraper respects the robots.txt file and rate limiting.
    The robots.txt is requested once for each domain.
    The robots.txt is consulted before any url from that domain enters the queue.
    Rate limiting is provided by a timestamp of the most recent request on that domain.
    The number of requests per domain is capped.
    """

    ssl._create_default_https_context = (
        ssl._create_unverified_context
    )  # rp.read req can throw error
    domain_d = {}  # Holds all robots.txts

    @timeout_decorator.timeout(constants.bot_excluder_timeout)
    def __init__(self, url, domain_dup):
        logger.info(f"new domain: {domain_dup}")
        self.rp = robotparser.RobotFileParser()
        self.last_req_ts = 0.0
        self.domain_count = 0
        self.dynamic_crawl_delay = self.rp.crawl_delay(
            "*"
        )  ## this will increase if error 429 detected

        # Get robots.txt
        self.set_robots_txt_path(url)
        try:
            self.rp.read()  # req
            logger.debug(
                f"rp printout: {self.rp.allow_all} {self.rp.disallow_all} {self.rp.can_fetch('*', '*')} {self.rp.url}"
            )
        except Exception as errex:
            logger.warning(f"__error: rp read: {domain_dup} {errex}")
            self.rp = None

        # Store rp so it is requested only once
        BotExcluder.domain_d[domain_dup] = self

    def set_robots_txt_path(self, url):
        """
        Create the robots.txt url
        """
        domain = get_domain(url)
        self.rp.set_url(parse.urljoin(domain, "robots.txt"))

    def update(self):
        """
        Update after each request on the domain.
        """
        # logger.debug(f"rp update start")
        self.last_req_ts = datetime.now().timestamp()
        self.domain_count += 1
        # logger.debug(f"rp update complete")

    def can_request(self, url):
        """
        Return True if all checks pass
        """
        if not self.rp_exist():
            logger.debug(f"rp not found: {url}")
            return True
        if all((self.ask_robots_txt(url), self.check_domain_occurrence_limiter(url))):
            return True

    def rp_exist(self):
        """
        Return True if a robots.txt has been found
        """
        if self.rp and len(self.rp.__str__()) > 1:
            return True

    def ask_robots_txt(self, url):
        """
        Return True if the robots.txt allows crawling
        """
        if not self.rp.can_fetch("*", url):
            logger.info(f"rp can not fetch: {url}")
            return False
        return True

    def get_rate_limit_wait(self):
        """
        Return the time needed to wait before the next request
        """
        if not self.rp_exist():
            return 0
        if not self.dynamic_crawl_delay:
            return 0
        time_elapsed = datetime.now().timestamp() - self.last_req_ts
        if self.dynamic_crawl_delay > 60:
            self.dynamic_crawl_delay = 60
        return self.dynamic_crawl_delay - time_elapsed

    def check_domain_occurrence_limiter(self, url):
        """
        Return True if the max number of requests for the domain has not been reached
        """
        if self.domain_count > constants.DOMAIN_LIMIT:
            logger.info(f"Domain limit exceeded: {url} {self.domain_count}")
            checked_urls_d_entry(get_url_dup(url), "Domain limit exceeded")
            return False
        return True

    def read_file():
        """
        Reuse the previous robots.txts to populate BotExcluder.domain_d
        """
        BotExcluder.domain_d = {}  # Default to empty
        try:
            with open(constants.RP_PATH, "rb") as rp_file:
                rp_d = pickle.load(rp_file)
                if BotExcluder.check_file_expiration(rp_d):
                    BotExcluder.domain_d = rp_d
        except Exception:
            logger.exception(f"RP file read failed:")

    def check_file_expiration(rp_d):
        """
        Return True if the previous robots.txts have not expired
        """
        # Get time robots.txt was fetched
        for i in rp_d.values():
            ts = i.rp.mtime()
            if ts:
                break
        else:
            logger.error("Error: cant recover any rp timestamp")
            return

        if datetime.now() - datetime.fromtimestamp(ts) > timedelta(
            days=constants.RP_EXPIRATION_DAYS
        ):
            logger.warning(f"rp_file outdated")
        else:
            logger.info(f"rp_file still valid")
            return True

    def write_file():
        """
        Save the robots.txts for future use because it's slow to request them all (synchronous)
        """
        with open(constants.RP_PATH, "wb") as rp_file:
            pickle.dump(BotExcluder.domain_d, rp_file)
        logger.info(f"RP file written")


class Blacklist:
    """
    Maintain a list of urls not to request because they will fail
    """

    # Combine recurring errors file and static blacklist
    def __init__(self):
        try:
            with open(constants.AUTO_BL_PATH, "r") as f:
                self.auto_blacklist_d = json.load(f)
        except Exception:
            logger.exception(f"cant open blacklist file")
            self.auto_blacklist_d = {}

        self.purge_auto_blacklist()
        Blacklist.combined_l = constants.STATIC_BLACKLIST + tuple(self.auto_blacklist_d)

    def purge_auto_blacklist(self):
        """
        Remove expired entries
        """
        rem_l = []
        for url, bl_date_s in self.auto_blacklist_d.items():
            bl_date_dt = date.fromisoformat(bl_date_s)
            if (
                bl_date_dt + timedelta(days=constants.BLACKLIST_EXPIRATION_DAYS)
                < date.today()
            ):
                rem_l.append(url)

        # Remove after iteration
        for url in rem_l:
            logger.info(f"Removing expired auto blacklist entry: {url} {bl_date_s}")
            del self.auto_blacklist_d[url]

    def update_auto_blacklist(self, recurring_errs_l):
        """
        Any urls that fail multiple times are added to the blacklist
        """
        for url in recurring_errs_l:
            url_dup = get_url_dup(url)
            self.auto_blacklist_d[url_dup] = date.today().isoformat()

        with open(constants.AUTO_BL_PATH, "w") as f:
            json.dump(self.auto_blacklist_d, f, indent=2)
        logger.info(f"Auto blacklist updated")


def make_dirs():
    """
    Create the folders for writing files
    """
    for db in constants.DB_TYPES:
        db_path = os.path.join(constants.RESULTS_PATH, db)
        if not os.path.exists(db_path):
            os.makedirs(db_path)

    # Dir for rp and autoblacklist files
    if not os.path.exists(constants.PERSISTENT_PATH):
        os.makedirs(constants.PERSISTENT_PATH)

    # Dir for error 7 files
    if not os.path.exists(constants.ERR7_PATH):
        os.makedirs(constants.ERR7_PATH)


def recover_progress():
    """
    Resume a scraping run using leftover results from the previously failed attempt.
    Populate a queue with all the remaining urls.
    """
    # pickle queue of class objs
    with open(constants.QUEUE_PATH, "rb") as f:
        Scrape.all_urls_q = pickle.load(f)
    Scrape.total_count = Scrape.all_urls_q.qsize()

    # errorlog as dict
    with open(constants.ERROR_PATH, "r") as f:
        Scrape.error_urls_d = json.load(f)
    logger.info(f"errorlog recovery complete")

    # CML as dict
    with open(constants.CHECKED_PATH, "r") as f:
        Scrape.checked_urls_d = json.load(f)
    logger.info(f"CML recovery complete")

    # multi_org_d as dict
    with open(constants.MULTI_ORG_D_PATH, "r") as f:
        Scrape.multi_org_d = json.load(f)
    logger.info(f"Scrape.multi_org_d recovery complete")

    logger.info(f"Progress recovery successful")


def start_fresh():
    """
    Start a new scraping run.
    Populate a queue with all the starting urls
    """
    logger.info(f"Using an original queue")

    Scrape.checked_urls_d = (
        {}
    )  # URLs that have been checked and their outcome (jbw conf, redirect, or error)
    Scrape.error_urls_d = {}  # URLs that have resulted in an error
    Scrape.multi_org_d = {
        "civ": {},
        "sch": {},
        "uni": {},
    }  # Nested dicts for multiple orgs covered by a URL
    Scrape.all_urls_q = asyncio.Queue()

    civ_db, sch_db, uni_db = read_dbs()

    for db, db_label in (civ_db, "civ"), (sch_db, "sch"), (uni_db, "uni"):
        init_queue(db, db_label)

    Scrape.total_count = Scrape.all_urls_q.qsize()


def read_dbs():
    """
    Get the starting urls from dict files
    """
    with open(constants.CIV_DB_PATH, "r") as f:
        civ_db = json.load(f)
    with open(constants.SCH_DB_PATH, "r") as f:
        sch_db = json.load(f)
    with open(constants.UNI_DB_PATH, "r") as f:
        uni_db = json.load(f)

    # Testing purposes
    """
    civ_db = [
    ["City of Albany", "https://jobs.albanyny.gov/jobopps", "http://www.albanyny.org"],
    ["City of Amsterdam", "https://www.amsterdamny.gov/Jobs.aspx", "http://www.amsterdamny.gov/"],
    ["City of fake", "https://jobs.albadfdggdgnyny.gov/jobopps", "http://www.albanyny.org"],
    ["Village of Fort Plain", "https://www.fortplain.org/contact-us/employment/", "https://www.fortplain.org/contact-us/employment/"]
    ]
    sch_db = []
    uni_db = []
    """

    return civ_db, sch_db, uni_db


def init_queue(db, db_label):
    """
    Put the starting URLs into the queue
    """
    for org_name, em_url, homepage in db:
        # Skip if em URL is missing or marked
        if not em_url:
            continue
        if em_url.startswith("_"):
            continue

        url_dup = get_url_dup(em_url)

        # If that url is already in queue then mark it as multi org. After scraper copy results to all other orgs using that url
        try:
            Scrape.multi_org_d[db_label][url_dup].append(
                org_name
            )  # Not first org using this URL
            logger.debug(f"Putting in multi org dict: {em_url}")
        except KeyError:
            Scrape.multi_org_d[db_label][url_dup] = [
                org_name
            ]  # First org using this URL

            # Put org name, em URL, initial crawl level, homepage, and jbws type into queue
            scrap = Scrape(org_name, em_url, 0, homepage, db_label, url_dup)
            if allow_into_q(em_url):  # respect robots.txt
                Scrape.all_urls_q.put_nowait(scrap)


def make_human_readable(arg_dict, path):
    """
    Convert dicts to a pretty format that can be read by humans and json
    """
    text = "{\n"
    for k, v in arg_dict.items():
        text += (
            json.dumps(k) + ": " + json.dumps(v) + ",\n\n"
        )  # json uses double quotes
    text = text[:-3]  # Remove trailing newlines and comma
    text += "\n}"
    with open(path, "w", encoding="utf8") as out_file:
        out_file.write(text)


def display_stats():
    """
    Stop the timer and display stats
    """
    duration = datetime.now() - startTime
    logger.info(f"\n\nPages checked = {Scrape.total_count}")
    logger.info(f"Duration = {round(duration.seconds / 60)} minutes")
    logger.info(
        f"Pages/sec/task = {str((Scrape.total_count / duration.seconds) / constants.SEMAPHORE)[:4]} \n"
    )


def multi_org_copy():
    """
    Allow one URL to cover multiple orgs.
    This is useful when an org has multiple campuses covered by one web page.
    """
    file_count = 0
    org_count = 0
    for db_type, url_d in Scrape.multi_org_d.items():
        for url, org_names_l in url_d.items():
            # URL is used by more than one org
            if len(org_names_l) > 1:
                src_path = os.path.join(
                    constants.RESULTS_PATH, db_type, org_names_l[0]
                )  # Path to results of first org in list

                # Check if results exists for first org
                if os.path.isdir(src_path):
                    logger.debug(f"Copying: {src_path}")

                    # Copy results from first org to all remaining orgs
                    for dst_path in org_names_l[1:]:
                        dst_path = os.path.join(
                            constants.RESULTS_PATH, db_type, dst_path
                        )
                        logger.debug(f"to:      {dst_path}")
                        try:
                            shutil.copytree(src_path, dst_path)
                        except Exception:
                            logger.exception(f"multiorg copy error")
                        file_count += 1
                    org_count += 1

                # this acts like a portal error for all other orgs in this list too. can also find these errors by finding multi_d orgs in the errorlog
                # Detect no results for first multi_d org
                else:
                    logger.info(f"multi_org portal errors: {org_names_l}")
    logger.info(f"\nMulti orgs: {org_count}")
    logger.info(f"Multi org files: {file_count}")


def fallback_to_old_results():
    """
    Reuse older results for any webpage that couldn't be retrieved
    """
    dater_d = glob(constants.JORB_HOME_PATH + "/*")  # List all date dirs
    if len(dater_d) < 2:
        return

    dater_d.sort(reverse=True)
    logger.info(f"\nFalling back to old results: {dater_d[1]}")
    old_dater_results_dir = os.path.join(dater_d[1], "results")

    for db_name in constants.DB_TYPES:
        cur_db_dir = os.path.join(constants.RESULTS_PATH, db_name)
        old_db_dir = os.path.join(old_dater_results_dir, db_name)

        cur_org_names_l = [os.path.basename(path) for path in glob(cur_db_dir + "/*")]
        old_org_names_l = [os.path.basename(path) for path in glob(old_db_dir + "/*")]

        missing_orgs_l = set(old_org_names_l) - set(cur_org_names_l)
        copy_old_results(db_name, missing_orgs_l, old_db_dir)


def copy_old_results(db_name, missing_orgs_l, old_db_dir):
    """
    Copy old org name dir to new include_old dir
    """
    inc_old_dir = os.path.join(constants.RESULTS_PATH, "include_old", db_name)
    logger.info(f"Files in /include_old: {len(glob(inc_old_dir))}")
    for org_name in missing_orgs_l:
        inc_org_name_path = os.path.join(inc_old_dir, org_name)

        if not os.path.exists(inc_org_name_path):  # copy will create dir
            old_org_name_path = os.path.join(old_db_dir, org_name)
            shutil.copytree(old_org_name_path, inc_org_name_path)
            logger.debug(f"Copied fallback result: {org_name}")

        # Catch errors
        else:
            logger.warning(f"Already exists: {inc_org_name_path}")


def send_to_server():
    """
    Copy results to the remote server using bash
    """
    # cmd_proc = subprocess.run(constants.PUSH_RESULTS_PATH, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    # logging.info(cmd_proc.stdout.decode("utf-8"))  # decode bytes to str
    logger.info(subprocess.getoutput(constants.PUSH_RESULTS_PATH))


class ContextFilter(logging.Filter):
    """
    Append the asyncio task id, if available, to the log
    """

    def filter(self, record):
        try:
            record.task_id = f"- {asyncio.current_task().get_name()}"
        except:
            record.task_id = ""
        return True


logger = logging.getLogger()


def config_logger():
    """
    The logger has a file handler and console handler.
    The file handler logs everything (DEBUG).
    The console handler logs INFO.
    """
    logger.setLevel(logging.DEBUG)

    file_handler = logging.FileHandler(constants.LOG_PATH, mode="a")
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        "%(asctime)s - %(levelname)s - %(message)s %(task_id)s", datefmt="%H:%M:%S"
    )
    file_handler.setFormatter(file_format)
    file_handler.addFilter(ContextFilter())

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_format = logging.Formatter("%(levelname)s - %(message)s")
    console_handler.setFormatter(console_format)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


"""
# Handle uncaught exceptions
def uncaught_handler(exctype, value, tb):
    logger.critical(f'------- UNCAUGHT {exctype}, {value}, {tb.tb_lineno}')
sys.excepthook = uncaught_handler
"""


if __name__ == "__main__":
    make_dirs()
    config_logger()
    blacklist_o = Blacklist()
    BotExcluder.read_file()

    try:
        recover_progress()
    except Exception as errex:
        logger.info(f"{errex}")
        start_fresh()

    BotExcluder.write_file()

    asyncio.run(main(), debug=False)

    display_stats()
    multi_org_copy()
    fallback_to_old_results()

    make_human_readable(Scrape.checked_urls_d, constants.CHECKED_PATH)
    make_human_readable(Scrape.error_urls_d, constants.ERROR_PATH)
    make_human_readable(Scrape.dynamic_db, constants.DYNAMIC_DB_PATH)

    send_to_server()

    import err_parse

    recurring_errs_l = err_parse.main()

    blacklist_o.update_auto_blacklist(recurring_errs_l)
