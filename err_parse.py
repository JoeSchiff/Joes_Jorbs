
# Desc: Parse JJ errorlog


# if hangs when supplying files, prob error with that file


# To do:
# switch to delim char. - where?
# count how many recoveries from each error
# always include a and b ? or just b?
# distinguish jj_error a and b for: 2-7
# merge with auto blacklist +
# switch to logging +
#   output kinda sloppy
# tally number of logger.warn, err, and exc +
# functions



from glob import glob
import json
import sys
import logging


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)


all_d = {}  # Dict for holding all errorlogs
using_l = []  # Only for convience

logger.info(f'\n Begin error parser')
logger.info(f'{sys.argv}')



def get_errorlogs():
    # No args. Use n most recent
    if len(sys.argv) == 1:
        num_files = 2
        dater = glob.glob("/home/joepers/joes_jorbs/*")  # where to find errorlogs
        dater.sort(reverse=True)

    else:
        # Use user-supplied number of files
        if sys.argv[1].isnumeric():
            logger.info(f'Using number of files: {num_files}')
            num_files = int(sys.argv[1])

        # Use user-supplied specific files
        else:
            num_files = len(sys.argv) - 1
            dater = sys.argv[1:]  # find errorlogs in args
            dater.sort(reverse=True)
            #logger.info(f'Using files:', dater)
get_errorlogs(num_files)


def read_errorlogs(num_files):
    dater_dir_pos = 0  ## combine with err_log_num
    # Loop through errorlogs up to specified amount
    for err_log_num in range(1, (num_files + 1)):

        # Try next errorlog on error
        while dater_dir_pos < num_files:

            # Read errorlog, save contents to all_d
            try:
                date_s = dater[dater_dir_pos].split('/')[4]
                with open(dater[dater_dir_pos] + '/errorlog', 'r') as f:
                    all_d[date_s] = json.loads(f.read())
                    logger.info(f'Using: {date_s}')
                    using_l.append(date_s)
                    dater_dir_pos += 1  # inc to next errorlog on pass or fail
                    break
            
            ## if any user speced files fails, it will be fatal error
            except Exception as errex:
                logger.info(f'some error: {errex} {sys.exc_info()[2].tb_lineno}')
                '''
                if 'Expecting property name enclosed in double quotes' in str(errex):
                    logger.info(f'Failed:', dater[dater_dir_pos].split('/')[4], 'prob due to partial scrape')
                else:
                    logger.info(f'Failed:', dater[dater_dir_pos].split('/')[4], errex)
                '''
                dater_dir_pos += 1  # inc to next errorlog on pass or fail
read_errorlogs(num_files)




fallback_l = []
jj_7a_l = []
jj_7b_l = []
jj_7c_l = []

# Init dicts with empty lists. Key names correspond to jj_error codes
total_d = {}
for i in range(1,10): total_d[str(i)] = []

final_d = {}
for i in range(1,10): final_d[str(i)] = []


# Tally all errors and final errors in first errorlog
for url, value in all_d[list(all_d)[0]].items():

    info_l = value[0]
    org_name = value[0][0]
    db_type = value[0][1]
    crawl_level = value[0][2]

    err_l = value[1]
    final_l = value[-1]


    for each_err in err_l:
        err_num = each_err[1].split('jj_error ')[1][0]  # Get error number from last error. exclude letter from 7b etc
        total_d[err_num].append(url)  # Tally all errors


    ## use only last err num? record all err nums?
    if 'jj_final_error' in final_l: final_d[err_num].append(url)  # Tally final errors

    if 'fallback_success' in final_l: fallback_l.append(url)  # Tally fallback successes

    # Tally jj_error 7 as separately
    if ["Empty vis text", "jj_error 7a"] in err_l: jj_7a_l.append(url)
    if ["Empty vis text", "jj_error 7b"] in err_l: jj_7b_l.append(url)




# Display error code summaries
logger.info(f'\njj_error 1: Crawler')
logger.info(f'jj_error 2: Non-HTML')
logger.info(f'jj_error 3: Request timeout')
logger.info(f'jj_error 4: HTTP 404 / 403')
logger.info(f'jj_error 5: Other request')
logger.info(f'jj_error 6: Unknown request')
logger.info(f'jj_error 7: Empty vis text')
logger.info(f'jj_error 8: Looper timeout')
logger.info(f'jj_error 9: Unknown looper')


# Errorlog1 total errors
logger.info(f'\n\n\n ------ Most recent errorlog: {using_l[0]} ------')
total = 0
max_val = max(len(x) for x in total_d.values())  # Length of longest value, most frequent error
logger.info(f'\nTotal errors:')
for k, v in total_d.items():
    row = k + ':', len(v), '', '=' * int(len(v) * 100 / max_val)  # Determine number of chars to represent as a percent of max_val
    logger.info(f'jj_error {"".join(str(word).ljust(4) for word in row)}')  # Format and pad each element in row list for pretty print
    total += len(v)
logger.info(f'total: {total}')

# Errorlog1 final errors
total = 0
#max_val = max(len(x) for x in final_d.values())  ## uncomment to not use previous max_val and scale
logger.info(f'\nFinal errors:')
for k, v in final_d.items():
    row = k + ':', len(v), '', '=' * int(len(v) * 100 / max_val)
    logger.info(f'jj_error {"".join(str(word).ljust(4) for word in row)}')
    total += len(v)
logger.info(f'total: {total}')




'''
logger.info(f'\nEmpty vis text errors:')
logger.info(f'jj_7a_tally:', len(jj_7a_l))
logger.info(f'jj_7b_tally:', len(jj_7b_l))

# URLs recovered from 7a error
for i in jj_7a_l:
    if not i in jj_7b_l: logger.info(fi)

logger.info(f'jj_7c_tally:', len(jj_7c_l), '\n\n')

# URLs recovered from 7b error
for i in jj_7b_l:
    if not i in jj_7c_l: logger.info(fi)
'''


fin_l_d = {}  # A list of final errors for each errorlog
all_fin_l = []  # Use this to count how many times a URL appears in the given errorlogs


# Put all final error URLs into one big list to find recurring error URLs
for date_name, errorlog in all_d.items():
    fin_l_d[date_name] = []
    for url_k, entry_v in errorlog.items():
        if 'jj_final_error' in entry_v[-1]:
            fin_l_d[date_name].append(url_k)
            all_fin_l.append(url_k)


logger.info(f'Fallback to homepage successes: {len(fallback_l)}')



# Number of final errors in each errorlog
logger.info(f'\n\n\n ------ All errorlogs: {using_l} ------')
logger.info(f'\nFinal errors:')
for k, v in fin_l_d.items():
    logger.info(f'{k}: {len(v)}')



# Find which URLs appear in all the errorlogs
rec_errs_l = []
for i in all_fin_l:
    if all_fin_l.count(i) == num_files:
        rec_errs_l.append(i)
    elif all_fin_l.count(i) > num_files:
        logger.info(f'\nthis should never happen\n')

rec_errs_l = list(dict.fromkeys(rec_errs_l))  # remove dups

# Display recurring final error URLs
logger.info(f'\n\nRecurring final errors: {len(rec_errs_l)} \n\n')

for i in rec_errs_l:
    logger.info(f'{i}')





with open(dater[0] + '/log_file', 'r') as f:
    log_file = f.read()

warning_count = log_file.count(' - WARNING - ')
error_count = log_file.count(' - ERROR - ')
critical_count = log_file.count(' - CRITICAL - ')

logger.info(f'\nWarning count: {warning_count}')
logger.info(f'Error count: {error_count}')
logger.info(f'Critical count: {critical_count}')










