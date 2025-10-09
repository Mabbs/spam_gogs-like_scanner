import asyncio
from curl_cffi import requests
from urllib.parse import urlparse

BASE_URL = "https://gitea.mpc-web.jp"
with open('gogs-like_instances.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()
checked_urls = set([line.strip().lower() for line in lines])

def get_url_before_path(url):
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else url

async def fetch_repo_links(session, base, page):
    try:
        resp = await session.get(base + f"/api/v1/repos/search?page={page}")
        response = resp.json()
        repo_links = []
        for repo in response.get("data", []):
            if "website" in repo.get("owner", {}):
                repo_links.append(repo["owner"]["website"])
        return repo_links
    except Exception as e:
        print(f"Error fetching page {page}: {e}")
        return []

async def is_gitea(session, url):
    try:
        resp = await session.get(url + "/api/v1/repos/search", timeout=5)
        data = resp.json()
        return data.get("ok", False)
    except Exception as e:
        # 网络错误、超时等
        # print(f"Error checking {url}: {e}")
        return False

def save_to_file(filename, data):
    with open(filename, 'a') as f:
        f.write(data + "\n")

async def process_page(session, page):
    print(f"Scanning page {page}...")
    repo_links = await fetch_repo_links(session, BASE_URL, page)
    tasks = []
    for spamlink in repo_links:
        if not spamlink:
            continue
        linked_url = get_url_before_path(spamlink).lower()
        if linked_url in checked_urls:
            continue
        checked_urls.add(linked_url)
        tasks.append(check_and_save(session, linked_url))
    await asyncio.gather(*tasks)

async def check_and_save(session, url):
    if await is_gitea(session, url):
        print(f"Found Gogs-like instance at: {url}")
        save_to_file("gogs-like_instances.txt", url)

async def main():
    async with requests.AsyncSession() as session:
        # 控制并发量（避免过载）
        semaphore = asyncio.Semaphore(20)

        async def bounded_process(page):
            async with semaphore:
                await process_page(session, page)

        await asyncio.gather(*(bounded_process(page) for page in range(1, 3334)))

if __name__ == "__main__":
    asyncio.run(main())
