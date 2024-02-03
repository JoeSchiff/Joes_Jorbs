

class Scrape:
    """
    Each webpage is represented by an instance of this class (called a scrap).

    Handles all URL processing before and after the HTTP request.
    """



class RequesterBase:
    """The URL requesting super class."""



class PwReq(RequesterBase):
    """
    The primary requester which uses Playwright.

    Responses will include dynamic content (JavaScript). 
    """


class PwPingReq(PwReq):
    """A specialized requester used only for checking network connectivity."""



class StaticReq(RequesterBase):
    """
    The fallback requester which uses aiohttp.

    This will be used if Playwright fails.

    Responses will not include dynamic content (JavaScript). 
    """




class BotExcluder:
    """
    Handles robots.txt compliance and domain-wide rate limiting across tasks.
    
    The robots.txt file for a domain is consulted before any URL is requested.
    Since urllib.robotparser is blocking, the robots.txt file is saved locally for performance reasons. Entries expire periodically.

    Rate limiting is achieved by storing the timestamp of the most recent request made to each domain.
    If an HTTP 429 error (too many requests) is detected, then the crawl delay is doubled.

    All the instances are stored in the domain_d class var.
    """






class Blacklist:
    """
    A URL will be blacklisted if both requesters fail on consecutive runs.
    There is also a manual blacklist in const.py.

    The blacklist is updated and saved locally after each run. Entries expire periodically.    
    """

    










