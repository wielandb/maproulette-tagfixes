import requests
from time import sleep
import random
import sys
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

    random.shuffle(elements)

    for element in tqdm(elements):
        print("Checking element: ", element["type"], "/", element["id"])
        if check_imgur_404(element["tags"]["image"]):
            tagChanges = {"image":None}
            if "source" in element["tags"]:
                if "anasonic" in element["tags"]["source"]:
                    tagChanges["source"] = None
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
