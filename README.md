# Joes_Jorbs
Search for jobs in New York State's Civil Service, public schools, and colleges.

<br/>
Code dump for http://joesjorbs.com


<br/><br/>

### Scraper features:
* asyncio
* playwright
* fallback to static requests
* save and resume progress
* skip checked pages
* domain and rate limits
* retry request on recoverable errors
* auto blacklist
* errorlog with summary
* crawl links if they likely contain relevant content
* monitor network connection with ping
* upload to remote server

<br/><br/>

### Scraper overview:
The program begins by initializing the queue with URLs from the database. The database stores the name of the organization, the portal URL (the webpage most likely to contain job postings on that domain), and the domain homepage (to be used as a fallback if the portal fails). Relevant data stored with these URL objects is updated as the scrape progresses.\
Asyncio tasks are then created and begin pulling URL objects from the queue in parallel.\
URLs are screened prior to being requested. The robots.txt file for that domain is consulted and respected.\
Playwright is used for the URL request so that Javascript/dynamic content is included. This ensures the data scraped is identical to what a human user would see. All iframes are recursively requested and scraped.\
If a Playwright error is detected, then the scraper will attempt the request using urllib.\
Relevant links are found and added to the queue. The links are considered relevant only if they contain a phrase indicating that webpage contains job postings.\
New URLs are screened prior to entry into the queue. URLs may be excluded because it has already been requested by another task, it is on the blacklist, the maximum number of attempts has been reached, etc.\
If the request is a success then the visible text from the webpage is saved to a file. This will be used by the webserver to search for job titles.\
If the request failed then the error is logged and determined to be final or temporary. The URL is put back in the queue if a retry is deemed appropriate.\
The task grabs a new URL object from the queue and the loop continues.\
The network connection and Playwright instance is monitored by pinging joesjorbs webserver. Scraping is paused and a replacement browser instance is created if a connection error is detected. The network interface is reset if a bash ping also fails.\
Important objects are written to disk periodically, so that if a fatal error occurs then scraping can be resumed without much loss of progress.\
When all tasks report the queue is empty then an errorlog summary is displayed, the blacklist is updated with new URLs which have indicated persistent errors, and the results are copied to the webserver. 

<br/><br/>

### Website overview:
The webserver has the text results from the scraper. The results are stored in a directory tree containing text files which store the visible text scraped from each webpage. \
The homepage takes the job title supplied by the user and searches through the results looking for a match in each text file. \
Positive matches are filtered based on the user's options. \
GIS coordinates are stored for every organization used in the scraper and every ZIP code in the state. Geographic distance is calculated by comparing these two points on a sphere the size of the Earth (adjusted for oblateness found at NYS latitude).\
These functions are completed by a CGI Python script.



<br/><br/><br/><br/>



















