import requests
from time import sleep
import random
import sys
import os
sys.path.append('../../shared')
import challenge_builder as mrcb
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(x, *args, **kwargs):
        return x

import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
import asyncio
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig

import bs4, re

import valueFinder as vf
import json

import base64

import appStrings

async def page(surl, html=False):
    browser_config = BrowserConfig(
        #headless=True,
        #use_managed_browser=True,
        #user_data_dir="C:\\Users\\wiela\\Documents\\GitHub\\maproulette-tagfixes\\challenges\\imgur404\\browser_user",
        #browser_type="chromium"
    )  # Default browser configuration
    run_config = CrawlerRunConfig(
        #screenshot=True,
        #screenshot_wait_for=14.0,
        #magic=True,
        #remove_overlay_elements=True,
    )   # Default crawl run configuration

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(
            url=surl,
            config=run_config
        )
        if result.success:
            if result.screenshot:
                with open("page.png", "wb") as f:
                    f.write(base64.b64decode(result.screenshot))
                sleep(10)
            if html:
                return result.html
            else:
                return result.markdown
        else:
            return "Getting page failed. Website was not reachable."




def get_website_as_markdown(url):
    return asyncio.run(page(url))

def get_website_as_html(url):
    return asyncio.run(page(url, html=True))


def check_imgur_404(link: str) -> bool:
    print("Checking imgur link: ", link)
    # Checking a link for if the image is not available anymore
    # We can do this by using the imgur oembed API, which returns a 200 if the image is available and a 403 if it is not.
    # For that, we check https://api.imgur.com/oembed.json?url=https://imgur.com/[image_id]
    # We need to extract the image id from the link, which is the part between the last / and the .jpg, or, if there is no .jpg, after the last /

    imgur_link = extract_imgur_id_from_link(link)
    if imgur_link is None:
        raise ValueError("No imgur link found in the string")
    # Get the api for that id
    api_url = f"https://api.imgur.com/oembed.json?url=https://imgur.com/{imgur_link}"
    # this url return json.
    # A valid (available) image returns something like this: {"version":"1.0","type":"rich","provider_name":"Imgur","provider_url":"https:\/\/imgur.com","width":540,"height":500,"html":"<blockquote class=\"imgur-embed-pub\" lang=\"en\" data-id=\"O14zPtk\"><a href=\"https:\/\/imgur.com\/O14zPtk\">turnstile<\/a><\/blockquote><script async src=\"\/\/s.imgur.com\/min\/embed.js\" charset=\"utf-8\"><\/script>"}
    # An invalid (unavailable) image returns something like this: {"data":{"error":"Invalid URL - forbidden","request":"\/oembed.json","method":"GET"},"success":false,"status":403}

    response = requests.get(api_url)
    if response.status_code == 200:
        # The image is available
        print("Image is available")
        return False
    elif response.status_code == 403:
        # The image is not available
        print("Image is not available")
        return True
    else:
        raise ValueError("Error while checking imgur link: ", link, response.status_code, response.text)


def extract_imgur_link_from_string(string: str) -> str:
    """
    Extracts the imgur link (which looks like e.g http://i.imgur.com/PCPiL7xl.jpg or http://i.imgur.com/PCPiL7xl.jpeg or https://imgur.com/PCPiL7xl) from a string.
    Returns the first imgur link found or None if no link is found.
    """
    pattern = r"(http|https):\/\/(i\.)?imgur\.com\/([a-zA-Z0-9]+)(\.jpg|\.jpeg|\.png)?"
    match = re.search(pattern, string)
    if match:
        # return the full link
        return match.group(0)
    else:
        # Try to find a link without http(s)://
        pattern = r"(i\.)?imgur\.com\/([a-zA-Z0-9]+)(\.jpg|\.jpeg|\.png)?"
        match = re.search(pattern, string)
        if match:
            # return the full link
            return "https://" + match.group(0)
        else:
            # return None if no link is found
            print("No imgur link found in string: ", string)
            raise ValueError("No imgur link found in string: ", string)
            return None



def extract_imgur_id_from_link(link: str) -> str:
    """
    Extracts the imgur id from a link.
    The id is the part between the last / and the .jpg, or, if there is no .jpg, after the last /.
    """
    # Check if the link ends with .jpg
    if link.endswith(".jpg"):
        return link.split("/")[-1].split(".")[0]
    else:
        return link.split("/")[-1]


def get_osm_history(osmtype: str, osmid: int) -> list:
    """Fetch full history of an OSM element"""
    base_url = "https://api.openstreetmap.org/api/0.6"
    url = f"{base_url}/{osmtype}/{osmid}/history"
    response = requests.get(url)
    if response.status_code != 200:
        print(f"Failed to get history for {osmtype}/{osmid}")
        return []
    return response.text

def find_tag_setter(osmtype: str, osmid: int, key: str, value: str) -> tuple:
    """
    Find who set a specific tag value and in which version.
    Returns (username, version) or (None, None) if not found.
    """
    history_xml = get_osm_history(osmtype, osmid)
    if not history_xml:
        return None, None
    
    soup = bs4.BeautifulSoup(history_xml, "xml")
    elements = soup.find_all(osmtype)
    
    # Go through versions in reverse to find when the tag was set
    for element in elements:
        version = int(element.get("version"))
        username = element.get("user")
        tags = element.find_all("tag")
        
        # Check if this version has our tag with the value
        for tag in tags:
            if tag.get("k") == key and tag.get("v") == value:
                return username, version
                
        # If we find a version where the tag doesn't exist or has different value,
        # then the next newer version (which we already checked) must have set it
        for tag in tags:
            if tag.get("k") == key and tag.get("v") != value:
                break
        else:
            # Tag not found in this version, so if we found it in a newer version,
            # that newer version must have set it
            continue
            
    return None, None

if __name__ == "__main__":
    # Load the elements from the JSON file matches.json
    
    vf.main()
    with open("matches.json", "r", encoding='utf-8') as f:
           elements = json.load(f)
    # Load the user reports from the JSON file user_reports.json
    #try:
    #    with open("user_reports.json", "r", encoding='utf-8') as f:
    #        user_reports = json.load(f)
    #except FileNotFoundError:
    user_reports = {}
    # Delete the content of the user_reports/ directory
    try:
        for filename in os.listdir("user_reports/"):
            os.remove(os.path.join("user_reports/", filename))
    except FileNotFoundError:
        pass
    
    # Dictionary to store user -> list of edits
    user_edits = {}

    challenge = mrcb.Challenge()
    random.shuffle(elements)

    for element in tqdm(elements):
        print("Checking element: ", element["type"], "/", element["id"])
        tagChanges = {}
        offendingKeyValues = {}
        # Check all tags for imgur URLs
        for tag_key, tag_value in element["tags"].items():
            if isinstance(tag_value, str) and "i.imgur.com" in tag_value:
                imgur_link = extract_imgur_link_from_string(tag_value)
                if check_imgur_404(imgur_link):
                    tagChanges[tag_key] = None
                    offendingKeyValues[tag_key] = tag_value
                    print(f"Found 404 imgur link in tag: {tag_key}")
                    
                    # Find who set this tag
                    username, version = find_tag_setter(element["type"], element["id"], tag_key, tag_value)
                    if username:
                        if username not in user_edits:
                            user_edits[username] = []
                        # Store the relevant edit with all relevant info
                        user_edits[username].append({
                            'type': element["type"],
                            'id': element["id"],
                            'version': version,
                            'key': tag_key,
                            'value': tag_value
                        })
                        # Save the user_edits to a file
                        with open("user_reports.json", "w", encoding='utf-8') as f:
                            json.dump(user_edits, f, indent=2, ensure_ascii=False)
                    else:
                        print(f"Could not find who set the tag {tag_key} for {element['type']}/{element['id']}")
        
        # Only create a task if we found tags to change
        if tagChanges:
            # Create a list of the keys and values to be changed, format the links as Reachable links, start every row with a dash and end it with a newline
            linkList = "\n".join([f"- {key}: {value}" for key, value in offendingKeyValues.items()])
            fullTagTable = mrcb.TagsAsMdTable(element["tags"])
            geom = mrcb.getElementCenterPoint(element)
            mainFeature = mrcb.GeoFeature.withId(
                element["type"],
                element["id"],
                geom,
                properties={"linkList": linkList, "fullTagTable": fullTagTable}
            )
            cooperativeWork = mrcb.TagFix(
                element["type"],
                element["id"],
                tagChanges
            )
            t = mrcb.Task(
                mainFeature,
                additionalFeatures=[],
                cooperativeWork=cooperativeWork
            )
            challenge.addTask(t)
            challenge.saveToFile("imgur404.json")
    
        # Create output directory if it doesn't exist
        os.makedirs("user_reports", exist_ok=True)
        
        # Create per-user files
        for username, edits in user_edits.items():
            filename = os.path.join("user_reports", f"{username}.txt")
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(str(appStrings.USER_REPORT_MESSAGE_START))
                for edit in edits:
                    # Create OSM web link to the specific version
                    osm_link = f"https://www.openstreetmap.org/{edit['type']}/{edit['id']}/history#{edit['version']}"
                    f.write(f"{osm_link} - tag '{edit['key']}' with value '{edit['value']}'\n")
                f.write(str(appStrings.USER_REPORT_MESSAGE_END))
