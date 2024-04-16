

class Video:
"""
Every video file is an instance of this class.
"""


class Frame:
"""
Every frame to be put in the queue is an instance of this class.
Includes the frame class provided by PyAV.
Includes a reference to its :class:`~Video`.
"""






def merge_input_files(result_file_l):
    """
    Used to skip videos that have already been processed.
    """



def set_tess_exe():
    """
    Confirm Tesseract location.
    Tesseract is included in the `tess` dir if using a frozen executable.
    Otherwise, it must be on the path or declared with `pytesseract.tesseract_cmd`.
    """


def checked_list_entry(video_path):
    """
    Append video name to the list of completed videos.
    """


def debug_end_early():
    """
    End the test early.
    """



def prevent_divide_by_zero():
    """
    Create default data to prevent a fatal error.
    """

















