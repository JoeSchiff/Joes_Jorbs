#!/usr/bin/python3

# Desc: Use webpage-supplied data to filter and display results


import cgitb

cgitb.enable()  # Display errors on webpage


import sys

sys.path.append("/home/joepers/.local/lib/python3.11/site-packages/")

import json
from cgi import FieldStorage
from datetime import datetime
from glob import glob
from math import sin, cos, sqrt, atan2, radians
import os
import regex
import zips


startTime = datetime.now()


def display_head():
    print("Content-type: text/html\n\n\n")  # Mandatory header for CGI

    print(
        """
    <!DOCTYPE html>
    <html lang="en-US">
    <head>
    <title>Joes Jorb\'s</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="shortcut icon" href="#">

    <style>

    /* All body elements */
    body {
      text-align: center;
      font-family: Arial;
      color: white;
      font-size: 20px;
    }

    /* All h3 elements */
    h3 {
      text-align: center;
    }

    /* Style the tab */
    .tab {
      overflow: hidden;
      border: 1px solid #ccc;
      background-color: #eee;
    }

    /* Style the tab buttons */
    .tab button {
      background-color: inherit;
      border: none;
      outline: none;
      cursor: pointer;
      padding: 10px 5%;
      font-size: 22px;
    }

    /* Style tab buttons on hover */
    .tab button:hover {
      background-color: #ddd;
    }

    /* Create an active tab button class */
    .tab button.active {
      background-color: #ccc;
    }

    /* Style the tab content */
    .tabcontent {
      text-align: left;
      white-space: nowrap;
      overflow: auto;
      display: none;
      padding: 6px 40px;
      border: 1px solid #ddd;
      #border-left: 12px solid #eee;
      border-top: none;
      background-color: #132020;
      font-size: 18px;
    }

    /* Make hyperlinks white */
    a {color: white;}

    </style>
    </head>
    """
    )


def display_body():
    print(
        """
    <body style="background-color: #0a1010;">
    <h2><a href="/index.html" style="text-decoration: none">Joe's Jorbs</a></h2>

    <!-- Call JS function to display tab content when tab is clicked -->
    <br><div class="tab">
        <button class="tablinks" onclick="open_tab_f(event, 'Results')" id="default_tab">&emsp;Results&emsp;</button>
        <button class="tablinks" onclick="open_tab_f(event, 'Pages_checked')">Pages checked</button>
        <button class="tablinks" onclick="open_tab_f(event, 'Domain_errors')">Domain errors</button>
        <button class="tablinks" onclick="open_tab_f(event, 'Errors')">Errors</button>
        <button class="tablinks" onclick="open_tab_f(event, 'Stats')">Stats</button>
    </div>
    """
    )


# Calculate distance between two coordinate pairs
def geodesic(home_coords, url_coords):
    try:
        radius = 3962  # Approximate radius of earth at 43N lat in miles

        lat1 = radians(home_coords[0])
        lon1 = radians(home_coords[1])
        lat2 = radians(url_coords[0])
        lon2 = radians(url_coords[1])
        dlon = lon2 - lon1
        dlat = lat2 - lat1
        a_mag = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c_mag = 2 * atan2(sqrt(a_mag), sqrt(1 - a_mag))
        dist = radius * c_mag
        return dist
    except:
        return 0


def get_db_types():
    civ_b = FieldStorage().getvalue("civ_cb")
    sch_b = FieldStorage().getvalue("sch_cb")
    uni_b = FieldStorage().getvalue("uni_cb")
    return civ_b, sch_b, uni_b


def build_keyword_list(keyword_array, keyword_list):
    if not isinstance(keyword_array, str):
        return keyword_list

    for keyword in keyword_array.split(
        "\x1f,"
    ):  # Split array into keywords based on delim char
        keyword = keyword.rstrip(
            "\x1f"
        ).lower()  # Try to remove delim char because the last kw in the array does not have a comma after
        if keyword and keyword not in keyword_list:
            keyword_list.append(keyword)

    return keyword_list


def get_keywords():
    keyword_list = []

    field_keyword = FieldStorage().getvalue(
        "kw_form"
    )  # Keyword remaining in the input field
    keyword_list = build_keyword_list(field_keyword, keyword_list)

    keyword_array_str = FieldStorage().getvalue(
        "kw_list"
    )  # Keyword(s) in array from "Enter" button
    keyword_list = build_keyword_list(keyword_array_str, keyword_list)

    return keyword_list


# Get the home ZIP code and coords
def get_coords():
    home_zip = FieldStorage().getvalue("zip_form")
    home_coords_form = FieldStorage().getvalue("coords_form")

    # Set blank ZIP to search all
    # print(home_zip)
    if not home_zip:
        home_zip = None
        max_dist = None
        home_coords = None

    # Get coords and max range
    else:
        try:
            home_coords = tuple(float(x) for x in home_coords_form.split(", "))
            max_dist = int(FieldStorage().getvalue("range_form"))
        except:
            home_coords = None
            max_dist = None

    return home_zip, home_coords, max_dist


def sort_keywords_into_fm_lists(keyword_list):
    # Lists containing keywords by keyword length
    zero_edits_l = []
    one_edits_l = []
    two_edits_l = []

    # Sort keywords into lists based on keyword length. Longer keywords get more regex edits
    for keyword in keyword_list:
        if len(keyword) > 17:
            two_edits_l.append(keyword)
        elif len(keyword) > 8:
            one_edits_l.append(keyword)
        else:
            zero_edits_l.append(keyword)

    return zero_edits_l, one_edits_l, two_edits_l


# Form regex pattern made of each item in keyword list
def create_regex_group(num_edits_l, num_edits):
    group_s = "("  # Enclose group in paren
    group_s += "|".join(num_edits_l)  # Separate each item with a pipe
    group_s += f"){{e<={num_edits}}}"  # use double curly to escape. max number of edits
    return group_s


def create_regex_pattern(keyword_list):
    if FieldStorage().getvalue("fuzz_cb"):
        reg_pat = ""
        zero_edits_l, one_edits_l, two_edits_l = sort_keywords_into_fm_lists(
            keyword_list
        )

        # Append 0 edit regex pattern(s)
        if zero_edits_l:
            reg_pat += create_regex_group(zero_edits_l, 0)

        # Append 1 edit regex pattern(s)
        if one_edits_l:
            if zero_edits_l:
                reg_pat += "|"  # separate from prev group
            reg_pat += create_regex_group(one_edits_l, 1)

        # Append 2 edit regex pattern(s)
        if two_edits_l:
            if zero_edits_l or one_edits_l:
                reg_pat += "|"
            reg_pat += create_regex_group(two_edits_l, 2)

    # Don't use fuzzy matching
    else:
        reg_pat = "|".join(keyword_list)

    reg_pat = regex.compile(reg_pat, regex.BESTMATCH)
    # reg_pat = regex.compile(reg_pat)
    return reg_pat


# Filter DB types
def select_db_dirs():
    dater = sorted(glob("/home/joe/*"), reverse=True)[0]  # Select most recent date dir
    dater_list = []  # db type directories to search
    display_db_l = []  # Used only in stats section

    # Create a list of db type dirs to search through
    if civ_b:
        dater_list.append(os.path.join(dater, "results", "civ/*"))
        dater_list.append(os.path.join(dater, "results", "include_old/civ/*"))
        display_db_l.append("Civ")
    if sch_b:
        dater_list.append(os.path.join(dater, "results", "sch/*"))
        dater_list.append(os.path.join(dater, "results", "include_old/sch/*"))
        display_db_l.append("Sch")
    if uni_b:
        dater_list.append(os.path.join(dater, "results", "uni/*"))
        dater_list.append(os.path.join(dater, "results", "include_old/uni/*"))
        display_db_l.append("Uni")

    return dater, dater_list, display_db_l


def get_zip_dict(db_type):
    if db_type == "civ":
        return zips.civ_d
    elif db_type == "sch":
        return zips.sch_d
    else:
        return zips.uni_d


def get_file_contents(fp):
    with open(fp, encoding="ascii", errors="ignore") as file:
        contents = file.read()
    jbw_conf, file_text = contents.split("\x1f")  # delim char
    return jbw_conf, file_text


def calc_percent_similarity(reg_res):
    num_edits = sum(
        reg_res.fuzzy_counts
    )  # Total substitutions, insertions, and deletions
    fuzzy_percent = round(
        len(reg_res.group()) / (len(reg_res.group()) + num_edits) * 100, 1
    )  # "group" is the matched str
    return fuzzy_percent


def get_url_from_path(file_path):
    url = file_path.split("/")[-1]
    return url.replace("%2F", "/")  # Restore forward slashes from percent encoding


def get_db_type(db_type_dir):
    db_type = db_type_dir.split("/")[5]
    if db_type == "include_old":
        return db_type_dir.split("/")[6]
    else:
        return db_type


def build_checked_list(dater_list):
    checked_list = []  # URLs that were searched

    for db_type_dir in dater_list:  # Each db type
        db_type = get_db_type(db_type_dir)
        db_zip_d = get_zip_dict(db_type)

        for org_name_dir in glob(db_type_dir):  # Each org dir in the db type dir
            org_name = org_name_dir.split("/")[-1]
            ## Use this to view which org names are a fallback from an older scraping (include_old dir)
            # org_name = str(org_name_dir.split('/')[-3:])[2:-2]

            # Only include orgs within range
            if home_coords and max_dist:
                dist = geodesic(home_coords, db_zip_d[org_name])
                if dist > max_dist:
                    continue

            # Select each URL text file
            for file_path in glob(os.path.join(org_name_dir, "*")):
                url = get_url_from_path(file_path)
                checked_list.append((org_name, file_path, url))

    return checked_list


def build_results_list(checked_list):
    res_list = []  # URLs with a keyword match

    for org_name, file_path, url in checked_list:
        jbw_conf, file_text = get_file_contents(file_path)
        reg_res = regex.search(
            reg_pat, file_text
        )  # Search text file for compiled pattern

        if reg_res:
            fuzzy_percent = calc_percent_similarity(reg_res)

            # Disallow match if below threshold. This is needed for short keywords
            if fuzzy_percent < 89:
                continue
            res_list.append(
                [org_name, url, jbw_conf, str(fuzzy_percent), reg_res.group()]
            )

    return sorted(
        res_list, key=lambda x: int(x[2]), reverse=True
    )  # Sort results by jbw conf


def display_results(res_list):
    print('<div id="Results" class="tabcontent" style="background-color: #132020">')
    print(
        f"<br>Keywords used: {str(keyword_list)[1:-1]} <h3> {len(res_list)} Matches found at:</h3>"
    )

    org_tracker_l = []  # To display org name only once
    url_tracker_l = []  # To display URL only once

    for org_name, url, jbw_conf, fuzzy_percent, match_s in res_list:
        if (
            org_name not in org_tracker_l and url not in url_tracker_l
        ):  # Display org name only once and only when a URL will be displayed
            print(f"<br><br><strong> {org_name} </strong>")
            org_tracker_l.append(org_name)
        if url not in url_tracker_l:
            print(
                f'<br>&emsp;&emsp;&emsp;&emsp;<a style="text-decoration:none;" href="{url}" title="Keyword match: {match_s}&#10;Percent similar: {fuzzy_percent}%">{url}</a>'
            )
            url_tracker_l.append(url)

    print("<br><br><br></div>")


def display_checked_pages(checked_list):
    print(
        f'<div id="Pages_checked" class="tabcontent"><br><h3>These {len(checked_list)} pages were successfully searched</h3>'
    )
    org_tracker_l = []

    for org_name, file_path, url in sorted(checked_list):
        if not org_name in org_tracker_l:
            print(f"<br><br><strong> {org_name} </strong>")
            org_tracker_l.append(org_name)
        print(
            f'<br>&emsp;&emsp;&emsp;&emsp;<a style="text-decoration:none;" href="{url}">{url}</a>'
        )
    print("<br><br><br></div>")


def read_error_file(dater):
    try:
        err_path = os.path.join(dater, "errorlog")
        with open(err_path, encoding="utf-8") as f:
            errorlog_d = json.loads(f.read())

    except Exception as errex:  # Use empty error file as fallback
        # print(errex)
        errorlog_d = {}

    return errorlog_d


# Sort errors to either portal or regular. Remove unnecessary errorlog info
def sort_error_urls(errorlog_d):
    port_err_l = []
    reg_err_l = []

    for url, err_v in errorlog_d.items():
        # Omit non final errors
        # This will also omit if fallback was a success because 'fallback_success' is in place of 'jj_final_error'
        if not err_v[-1][-1] == "jj_final_error":
            continue

        db_type = err_v[0][1]
        org_name = err_v[0][0]

        # Sort errors to portal or regular based on crawl level
        if (
            err_v[0][2] == 0
        ):  # change to "< 1" to include domain fallback urls. this would cause dups?
            if not [url, db_type, org_name] in port_err_l:
                port_err_l.append([url, db_type, org_name])
        else:
            reg_err_l.append([url, db_type, org_name])

    return port_err_l, reg_err_l


# For portal and regular errors
def build_error_lists(err_l):
    filtered_l = []

    for url, db_type, org_name in err_l:
        db_zip_d = get_zip_dict(db_type)

        if home_coords and max_dist:
            dist = geodesic(home_coords, db_zip_d[org_name])
            if dist > max_dist:
                continue

        filtered_l.append([org_name, url])

    return filtered_l


def display_portal_errors(port_err_display_l):
    print(
        f'<div id="Domain_errors" class="tabcontent"><br><h3>The program was unable to search any webpages on these {len(port_err_display_l)} domains</h3>'
    )

    for org_name, url in port_err_display_l:
        print(f"<br><br><strong> {org_name} </strong>")
        print(
            f'<br>&emsp;&emsp;&emsp;&emsp;<a style="text-decoration:none;" href="{url}">{url}</a>'
        )

    print("<br><br><br></div>")


def display_reg_errors(reg_err_display_l):
    print(
        f'<div id="Errors" class="tabcontent"><br><h3>The program was unable to search these {len(reg_err_display_l)} webpages</h3>'
    )
    org_tracker_l = []  # Use this only to display org name once

    for org_name, url in reg_err_display_l:
        if not org_name in org_tracker_l:
            print(f"<br><br><strong> {org_name} </strong>")
            org_tracker_l.append({org_name})
        try:
            print(
                f'<br>&emsp;&emsp;&emsp;&emsp;<a style="text-decoration:none;" href="{url}">{url}</a>'
            )
        except Exception as errex:
            print(errex)

    print("<br><br><br></div>")


def calc_error_rate(checked_list, reg_err_display_l, port_err_display_l):
    if len(checked_list) < 1:
        error_rate = 0
    else:
        error_rate = (len(reg_err_display_l) + len(port_err_display_l)) / len(
            checked_list
        )

    if error_rate < 0.05:
        error_rate_desc = "(low)"
    elif error_rate < 0.15:
        error_rate_desc = "(medium)"
    else:
        error_rate_desc = "(high)"

    if len(errorlog_d) < 1:
        error_rate_desc = "No error dict"

    return error_rate, error_rate_desc


def display_stats(
    keyword_list,
    dater,
    display_db_l,
    home_zip,
    home_coords,
    max_dist,
    checked_list,
    port_err_display_l,
    port_err_l,
    reg_err_display_l,
    reg_err_l,
    error_rate,
    error_rate_desc,
    reg_pat,
):
    duration = round((datetime.now() - startTime).total_seconds(), 1)
    print(
        """<div id="Stats" class="tabcontent"><br><h3>Parameters and stats</h3><strong>
    <br>Keywords used:""",
        str(keyword_list)[1:-1],
        "<br>Scraping date:",
        dater.split("/")[-1],
        "<br>Databases:",
        display_db_l,
        "<br>ZIP code:",
        home_zip,
        "<br>Coordinates:",
        home_coords,
        "<br>Max distance:",
        max_dist,
        "miles<br><br>Pages searched:",
        len(checked_list),
        "<br>Domain errors:",
        len(port_err_display_l),
        "(out of",
        str(len(port_err_l)) + ")<br>Other errors:",
        len(reg_err_display_l),
        "(out of",
        str(len(reg_err_l)) + ")<br>Total error rate:",
        f"{round(error_rate * 100, 1)}%",
        error_rate_desc,
        "<br>Script duration:",
        duration,
        "seconds",
        "<br>Regex pattern:",
        reg_pat.pattern,
        "<br><br><br></strong></div>",
    )


# Display tab contents when a tab button is clicked
def display_current_tab_js():
    print(
        """
    <script>
    document.getElementById("default_tab").click(); // Display Results tab content by default

    function open_tab_f(event, tab_name) {
      var i, tabcontent, tablinks; // Declare vars
      tabcontent = document.getElementsByClassName("tabcontent"); // Get all tab elements
      for (i = 0; i < tabcontent.length; i++) { // Loop through all tab elements
        tabcontent[i].style.display = "none"; // Hide each tab element
      }
      tablinks = document.getElementsByClassName("tablinks"); // Get all tab buttons
      for (i = 0; i < tablinks.length; i++) { // Loop through all tab buttons
        tablinks[i].className = tablinks[i].className.replace(" active", ""); // Declare each tab button not active
      }
      document.getElementById(tab_name).style.display = "block"; // Display active tab contents
      event.currentTarget.className += " active"; // Declare active tab to stylize tab button
    }
    </script>
    """
    )


def display_other_links():
    print('<br><br><br><a href="/index.html">Start another search</a>')
    print('&emsp;&emsp;&emsp;&emsp;<a href="/help.html">Help</a>')

    print("<br><br></body></html>")


if __name__ == "__main__":
    display_head()
    display_body()

    civ_b, sch_b, uni_b = get_db_types()

    keyword_list = get_keywords()
    reg_pat = create_regex_pattern(keyword_list)

    home_zip, home_coords, max_dist = get_coords()
    dater, dater_list, display_db_l = select_db_dirs()

    checked_list = build_checked_list(dater_list)
    res_list = build_results_list(checked_list)

    display_results(res_list)
    display_checked_pages(checked_list)

    errorlog_d = read_error_file(dater)
    port_err_l, reg_err_l = sort_error_urls(errorlog_d)

    port_err_display_l = build_error_lists(port_err_l)
    reg_err_display_l = build_error_lists(reg_err_l)

    display_portal_errors(port_err_display_l)
    display_reg_errors(reg_err_display_l)

    error_rate, error_rate_desc = calc_error_rate(
        checked_list, reg_err_display_l, port_err_display_l
    )

    display_stats(
        keyword_list,
        dater,
        display_db_l,
        home_zip,
        home_coords,
        max_dist,
        checked_list,
        port_err_display_l,
        port_err_l,
        reg_err_display_l,
        reg_err_l,
        error_rate,
        error_rate_desc,
        reg_pat,
    )

    display_current_tab_js()
    display_other_links()
