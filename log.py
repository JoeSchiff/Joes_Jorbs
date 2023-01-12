

# Desc: get started



# todo
# can include funcName, lineno
# use f strings: logging.error(f'{name} raised an error')
# logging.exception() is like calling logging.error(exc_info=True)
#   except Exception as e: logging.exception("Exception occurred")







import logging, sys


logger = logging.getLogger(__name__)


fp = r"C:\Users\jschiffler\Desktop\log.txt"
f_handler = logging.FileHandler(fp, mode='a')
f_handler.setLevel(logging.INFO)
f_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%H:%M:%S')
f_handler.setFormatter(f_format)

c_handler = logging.StreamHandler()
c_handler.setLevel(logging.WARNING)
c_format = logging.Formatter('%(levelname)s - %(message)s')
c_handler.setFormatter(c_format)

logger.addHandler(f_handler)
logger.addHandler(c_handler)


logger.debug('This is a debug message')
logger.info('This is an info message')
logger.warning('This is a warning message')
logger.error('This is an error message')
logger.critical('This is a critical message')


# Handle uncaught exceptions
def uncaught_handler(exctype, value, tb):
    #logger.exception("Uncaught exception: {0}".format(str(value)))
    logger.critical(f'------- UNCAUGHT {exctype}, {value}, {tb.tb_lineno}')

sys.excepthook = uncaught_handler


























