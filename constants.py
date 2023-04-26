

import os
import re
from datetime import date

JORB_HOME_PATH = '/home/joepers/joes_jorbs'

DATER_PATH = os.path.join(JORB_HOME_PATH, date.today().isoformat())

RESULTS_PATH = os.path.join(DATER_PATH, 'results')
QUEUE_PATH = os.path.join(DATER_PATH, 'queue')
CHECKED_PATH = os.path.join(DATER_PATH, 'checked_pages')
ERROR_PATH = os.path.join(DATER_PATH, 'errorlog')
MULTI_ORG_D_PATH = os.path.join(DATER_PATH, 'multi_org_d')
LOG_PATH = os.path.join(DATER_PATH, 'log_file')
ERR7_PATH = os.path.join(DATER_PATH, 'jj_error_7')

PERSISTENT_PATH = os.path.join(JORB_HOME_PATH, '.persistent')
RP_PATH = os.path.join(PERSISTENT_PATH, 'rp_file')
AUTO_BL_PATH = os.path.join(PERSISTENT_PATH, 'auto_blacklist')


DB_TYPES = ('civ', 'sch', 'uni')


# Scraper options
MAX_CRAWL_DEPTH = 1  # Webpage recursion depth
SEMAPHORE = 12  # Num of concurrent tasks
EMPTY_CUTOFF = 200  # Num of characters in webpage text file to be considered empty
DOMAIN_LIMIT = 20  # Max num of pages per domain
RP_EXPIRATION_DAYS = 180
USER_AGENT_S = 'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/111.0'  ## used for only static req?




# Exclude links that contain any of these. percent encodings must be lower case
BUNKWORDS = ('academics', '5il.co', '5il%2eco', 'pnwboces.org', 'recruitfront.com', 'schoolapp.wnyric.org', 'professional development', 'career development', 'javascript:', '.pdf', '.jpg', '.ico', '.rtf', '.doc', '.mp4', '%2epdf', '%2ejpg', '%2eico', '%2ertf', '%2edoc', '%2emp4', 'mailto:', 'tel:', 'icon', 'description', 'specs', 'specification', 'guide', 'faq', 'images', 'exam scores', 'resume-sample', 'resume sample', 'directory', 'pupil personnel')

# Always skip these pages
STATIC_BLACKLIST = ('cc.cnyric.org/districtpage.cfm?pageid=112', 'co.essex.ny.us/personnel', 'co.ontario.ny.us/94/human-resources', 'countyherkimer.digitaltowpath.org:10069/content/departments/view/9:field=services;/content/departmentservices/view/190', 'countyherkimer.digitaltowpath.org:10069/content/departments/view/9:field=services;/content/departmentservices/view/35', 'cs.monroecounty.gov/mccs/lists', 'herkimercounty.org/content/departments/view/9:field=services;/content/departmentservices/view/190', 'herkimercounty.org/content/departments/view/9:field=services;/content/departmentservices/view/35', 'jobs.albanyny.gov/default/jobs', 'monroecounty.gov/hr/lists', 'monroecounty.gov/mccs/lists', 'mycivilservice.rocklandgov.com/default/jobs', 'niagaracounty.com/employment/eligible-lists', 'ogdensburg.org/index.aspx?nid=345', 'penfield.org/multirss.php', 'tompkinscivilservice.org/civilservice/jobs', 'tompkinscivilservice.org/civilservice/jobs', 'swedishinstitute.edu/employment-at-swedish-institute', 'sunyacc.edu/job-listings')


# Include links that include any of these
# Set high and low confidence jbw lists
JBWS_ALL_HIGH = ('continuous recruitment', 'employment', 'job listing', 'job opening', 'job posting', 'job announcement', 'job opportunities', 'job vacancies', 'jobs available', 'available positions', 'open positions', 'available employment', 'career opportunities', 'employment opportunities', 'current vacancies', 'current job', 'current employment', 'current opening', 'current posting', 'current opportunities', 'careers at', 'jobs at', 'jobs @', 'work at', 'employment at', 'find your career', 'browse jobs', 'search jobs', 'vacancy postings', 'vacancy list', 'prospective employees', 'help wanted', 'work with', 'immediate opportunities', 'promotional announcements')
JBWS_ALL_LOW = ('join', 'job', 'job seeker', 'job title', 'positions', 'careers', 'human resource', 'personnel', 'vacancies', 'vacancy', 'posting', 'opening', 'recruitment')

JBWS_CIV_HIGH = JBWS_ALL_HIGH + ('upcoming exam', 'exam announcement', 'examination announcement', 'examinations list', 'civil service opportunities', 'civil service exam', 'civil service test', 'current civil service', 'open competitive', 'open-competitive')

JBWS_CIV_LOW = JBWS_ALL_LOW + ('open to', 'civil service', 'exam', 'examination', 'test', 'current exam')

JBWS_SU_HIGH = JBWS_ALL_HIGH
JBWS_SU_LOW = JBWS_ALL_LOW
JBWS_SU_X_LOW = ('faculty', 'staff', 'adjunct', 'academic', 'support', 'instructional', 'administrative', 'professional', 'classified', 'coaching')  ## unused third tier?



# Compile regex paterns for reducing whitespace in written files
WHITE_REG = re.compile("\s{2,}")

# Compile regex paterns for removing hidden HTML elements
STYLE_REG = re.compile("(display\s*:\s*(none|block);?|visibility\s*:\s*hidden;?)")
CLASS_REG = re.compile('(hidden-sections?|dropdown|has-dropdown|sw-channel-dropdown|dropdown-toggle)')
 










