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


async def page(surl, html=False):
    browser_config = BrowserConfig()  # Default browser configuration
    run_config = CrawlerRunConfig()   # Default crawl run configuration

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(
            url=surl,
            config=run_config
        )
        if result.success:
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
    
    sitehtml = get_website_as_html(link)

    soup = bs4.BeautifulSoup(sitehtml, "html.parser")

    # PRIMARY TEST – layout class
    if soup.select_one(".GalleryCover"):
        print("GalleryCover detected")
        return False
    if soup.select_one(".HomeCover"):
        print("HomeCover detected")
        return True

    # SECOND TEST – og:url
    og = soup.find("meta", attrs={"property": "og:url"})
    if og and og["content"].rstrip("/") == "https://imgur.com":
        print("og:url detected")
        return True


    # default to 'exists' if none of the negative tests fired
    return False

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
    for element in reversed(elements):
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
    op = mrcb.Overpass()

    elements = op.getElementsFromQuery(
        """
        [out:json][timeout:250];
        nwr["image"~"i.imgur.com"];
        out tags center;
        """
    )
    challenge = mrcb.Challenge()
    
    # Dictionary to store user -> list of problematic edits
    user_edits = {}

    random.shuffle(elements)

    for element in tqdm(elements):
        print("Checking element: ", element["type"], "/", element["id"])
        tagChanges = {}
        
        # Check all tags for imgur URLs
        for tag_key, tag_value in element["tags"].items():
            if isinstance(tag_value, str) and "i.imgur.com" in tag_value:
                if check_imgur_404(tag_value):
                    tagChanges[tag_key] = None
                    print(f"Found 404 imgur link in tag: {tag_key}")
                    
                    # Find who set this tag
                    username, version = find_tag_setter(element["type"], element["id"], tag_key, tag_value)
                    if username:
                        if username not in user_edits:
                            user_edits[username] = []
                        # Store the problematic edit with all relevant info
                        user_edits[username].append({
                            'type': element["type"],
                            'id': element["id"],
                            'version': version,
                            'key': tag_key,
                            'value': tag_value
                        })
        
        # Only create a task if we found tags to change
        if tagChanges:
            geom = mrcb.getElementCenterPoint(element)
            mainFeature = mrcb.GeoFeature.withId(
                element["type"],
                element["id"],
                geom,
                properties={}
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
                for edit in edits:
                    # Create OSM web link to the specific version
                    osm_link = f"https://www.openstreetmap.org/{edit['type']}/{edit['id']}/history#{edit['version']}"
                    f.write(f"{osm_link} - tag '{edit['key']}' with value '{edit['value']}'\n")
