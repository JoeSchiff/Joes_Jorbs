# Desc: Parse JJ errorlogs. Deeper analyses performed on most recent (primary) errorlog

# Args: Supply integer to consider N most recent errorlogs. Or supply paths to files.


# To do:
# distinguish jj_error a and b for errs 2-7
#   how display?
# switch to logging +
#   set levels
#   remove name from output +
#   remove level from output when imported. - prob inherits log level of scraper
# errorlog suffers from poor structure. switch to named attrs not nested lists


from glob import glob
import json
import os
import sys
import logging


logging.basicConfig(level=logging.DEBUG, format="%(message)s")
logger = logging.getLogger(__name__)

logger.info(f"\n Begin error parser")


def display_err_descriptions():
    logger.info(f"\njj_error 1: Crawler")
    logger.info(f"jj_error 2: Non-HTML")
    logger.info(f"jj_error 3: Request timeout")
    logger.info(f"jj_error 4: HTTP 404 / 403")
    logger.info(f"jj_error 5: Other HTTP")
    logger.info(f"jj_error 6: Other request")
    logger.info(f"jj_error 7: Empty vis text")
    logger.info(f"jj_error 8: Looper timeout")
    # logger.info(f'jj_error 9: (reserved)')


def get_options():
    logger.info(f"Args: {sys.argv[1:]}")
    if len(sys.argv) == 1:
        logger.info(f"Using default options")
        num_files = 2
        date_dir = glob("/home/joepers/joes_jorbs/*")
    else:
        if len(sys.argv) == 2 and sys.argv[1].isnumeric():
            logger.info(f"Using number of files")
            num_files = int(sys.argv[1])
            date_dir = glob("/home/joepers/joes_jorbs/*")

        else:
            logger.info(f"Using specific files")
            num_files = len(sys.argv) - 1
            date_dir = sys.argv[1:]

    return num_files, sorted(date_dir, reverse=True)


def read_errorlogs(num_files, date_dir):
    all_errorlog_d = {}
    for err_log_num in range(num_files):
        try:
            date_s = date_dir[err_log_num].split("/")[4]
            with open(date_dir[err_log_num] + "/errorlog", "r") as f:
                all_errorlog_d[date_s] = json.loads(f.read())
                logger.info(f"Using: {date_s}")

        except Exception as errex:
            logger.info(f"error: {errex} {sys.exc_info()[2].tb_lineno}")
            """
            if 'Expecting property name enclosed in double quotes' in str(errex):
                logger.info(f'Failed:', dater[dater_dir_pos].split('/')[4], 'prob due to partial scrape')
            else:
                logger.info(f'Failed:', dater[dater_dir_pos].split('/')[4], errex)
            """
    if len(all_errorlog_d) < 1:
        logger.info(f"No errorlogs have been read. Exiting ...")
        sys.exit()
    return all_errorlog_d


# Key numbers correspond to jj_error codes
def init_tally_dicts():
    total_err_d = {}
    final_err_d = {}
    for i in range(1, 9):
        total_err_d[str(i)] = []
        final_err_d[str(i)] = []
    return total_err_d, final_err_d


def get_most_recent_errorlog(all_errorlog_d):
    errorlog_name = list(all_errorlog_d)[0]
    logger.info(f"\n\n ------------ Most recent errorlog: {errorlog_name} ------------")
    return all_errorlog_d[errorlog_name]


def get_err_num(each_err):
    return each_err[1].split("jj_error ")[1][
        0
    ]  # final index operator excludes letter from 7b etc


def build_tally_lists(primary_errorlog):
    total_err_d, final_err_d = init_tally_dicts()
    fallback_l = []
    jj_7a_l = []
    jj_7b_l = []

    for url, err_nested_l in primary_errorlog.items():
        err_l = err_nested_l[1]
        desc_l = err_nested_l[-1]

        total_err_d = tally_total_errors(err_l, url, total_err_d)
        last_err_num = get_err_num(err_l[-1])
        final_err_d = tally_final_errors(desc_l, url, last_err_num, final_err_d)

        fallback_l = tally_fallbacks(desc_l, url, fallback_l)
        jj_7a_l, jj_7b_l = tally_error_7(err_l, jj_7a_l, jj_7b_l, url)

    logger.info(f"\nFallback to homepage successes: {len(fallback_l)}")
    count_error_7_recoveries(jj_7a_l, jj_7b_l)

    return total_err_d, final_err_d


def tally_total_errors(err_l, url, total_err_d):
    for each_err in err_l:
        err_num = get_err_num(each_err)
        total_err_d[err_num].append(url)
    return total_err_d


def tally_final_errors(desc_l, url, err_num, final_err_d):
    if "jj_final_error" in desc_l:
        final_err_d[err_num].append(url)
    return final_err_d


def tally_fallbacks(desc_l, url, fallback_l):
    if "fallback_success" in desc_l:
        fallback_l.append(url)
    return fallback_l


def tally_error_7(err_l, jj_7a_l, jj_7b_l, url):
    if ["Empty vis text", "jj_error 7a"] in err_l:
        jj_7a_l.append(url)
    if ["Empty vis text", "jj_error 7b"] in err_l:
        jj_7b_l.append(url)
    return jj_7a_l, jj_7b_l


def count_error_7_recoveries(jj_7a_l, jj_7b_l):
    logger.info(f"\n\tEmpty vis text errors")
    logger.info(f"7a tally: {len(jj_7a_l)}")
    logger.info(f"7b tally: {len(jj_7b_l)}")

    recovered_urls = set(jj_7a_l) - set(jj_7b_l)
    logger.info(f"Recovered vis text errors: {len(recovered_urls)}\n")


def display_histogram_of_errors(name, err_d):
    logger.info(f"\n\t{name} errors:")
    total = 0
    max_val = max(len(x) for x in err_d.values())  # Highest tally, most frequent error
    for err_num, url_l in err_d.items():
        error_tally = len(url_l)
        total += error_tally
        padded_tally = str(error_tally).ljust(
            4
        )  # ljust() is number of spaces to use for padding
        percent_of_max = int(
            error_tally * 100 / max_val
        )  # Determine number of chars to represent the number of errors
        bar = "=" * percent_of_max  # Char representation of bar
        logger.info(f"jj_error {err_num}:  {padded_tally} {bar}")

    logger.info(f"     total:  {total}")


def get_all_final_errors(all_errorlog_d):
    final_err_l_d = {}  # Final errors for each errorlog
    for date_name, errorlog in all_errorlog_d.items():
        final_err_l_d[date_name] = []
        for url, err_l in errorlog.items():
            if "jj_final_error" in err_l[-1]:
                final_err_l_d[date_name].append(url)
    return final_err_l_d


def count_logging_levels(date_dir):
    log_file = os.path.join(date_dir[0], "log_file")
    with open(log_file, "r") as f:
        log_file = f.read()

    warning_count = log_file.count(" - WARNING - ")
    error_count = log_file.count(" - ERROR - ")
    critical_count = log_file.count(" - CRITICAL - ")

    logger.info(f"\n\n\tLogging level counts")
    logger.info(f'{"Warning:".ljust(9)} {warning_count}')
    logger.info(f'{"Error:".ljust(9)} {error_count}')
    logger.info(f'{"Critical:".ljust(9)} {critical_count}')


def count_final_errors(final_err_l_d):
    logger.info(f"\n\n\n ------------ All errorlogs ------------")
    logger.info(f"\nFinal errors:")
    for date_name, url_l in final_err_l_d.items():
        logger.info(f"{date_name}: {len(url_l)}")


def get_recurring_final_errors(final_err_l_d):
    """
    recurring_errs_l = []
    for url in list(final_err_l_d.values())[0]:  # use any list because url must be in all anyways
        if all(url in errorlog for errorlog in final_err_l_d.values()):
            recurring_errs_l.append(url)
    """

    recurring_errs_l = list(set.intersection(*map(set, final_err_l_d.values())))

    logger.info(f"\nRecurring final errors: {len(recurring_errs_l)} \n\n")
    # for i in recurring_errs_l: print(i)

    return recurring_errs_l


def main():
    num_files, date_dir = get_options()
    all_errorlog_d = read_errorlogs(num_files, date_dir)
    display_err_descriptions()

    # Analyse primary errorlog only
    primary_errorlog = get_most_recent_errorlog(all_errorlog_d)
    total_err_d, final_err_d = build_tally_lists(primary_errorlog)
    display_histogram_of_errors("All", total_err_d)
    display_histogram_of_errors("Final", final_err_d)
    count_logging_levels(date_dir)

    # Analyse all errorlogs
    final_err_l_d = get_all_final_errors(all_errorlog_d)
    count_final_errors(final_err_l_d)
    recurring_errs_l = get_recurring_final_errors(final_err_l_d)

    return recurring_errs_l


if __name__ == "__main__":
    main()
