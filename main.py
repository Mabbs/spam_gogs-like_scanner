import asyncio
from curl_cffi import requests
from urllib.parse import urlparse
import os

# load instances that will be used as base URLs for scanning
with open('gogs-like_instances.txt', 'r', encoding='utf-8') as f:
    instances = [line.strip().lower() for line in f if line.strip()][::-1]  # reverse to prioritize newer entries

# keep track of which base urls we have already verified reachable
checked_instances = set()

# track checked repo owner websites, and invalid ones to avoid rechecking
checked_urls = set()
invalid_urls = set()

# 加载无效网站和无效实例
if os.path.exists('invalid_sites.txt'):
    with open('invalid_sites.txt', 'r', encoding='utf-8') as f:
        for line in f:
            url = line.strip().lower()
            if url:
                invalid_urls.add(url)
if os.path.exists('invalid_instances.txt'):
    with open('invalid_instances.txt', 'r', encoding='utf-8') as f:
        for line in f:
            url = line.strip().lower()
            if url:
                invalid_urls.add(url)

# persist initially known URLs from file so we don't rescan duplicates
for url in instances:
    checked_urls.add(url)

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

async def process_page(session, base, page):
    print(f"Scanning {base} page {page}...")
    repo_links = await fetch_repo_links(session, base, page)
    tasks = []
    for spamlink in repo_links:
        if not spamlink:
            continue
        linked_url = get_url_before_path(spamlink).lower()
        if linked_url in checked_urls or linked_url in invalid_urls:
            continue
        checked_urls.add(linked_url)
        tasks.append(check_and_save(session, linked_url))
    await asyncio.gather(*tasks)

async def check_and_save(session, url):
    # if a url is unreachable, log and skip next time
    try:
        ok = await is_gitea(session, url)
    except Exception:
        ok = False
    if ok:
        print(f"Found Gogs-like instance at: {url}")
        save_to_file("gogs-like_instances.txt", url)
    else:
        invalid_urls.add(url)
        save_to_file("invalid_sites.txt", url)

async def get_total_pages(session, base):
    """Query the first search page and inspect headers to determine how many pages
    exist.  The API returns a `Link` header with a `rel="last"` entry, or an
    `X-Total-Count` header which can be divided by the number of items seen on
    page 1.
    """
    try:
        resp = await session.get(base + "/api/v1/repos/search?page=1")
        # look for a last link in the header
        link = resp.headers.get("Link", "")
        if link:
            # Example: <.../search?page=2>; rel="next",<.../search?page=448>; rel="last"
            for part in link.split(","):
                if "rel=\"last\"" in part:
                    # extract page=NUMBER
                    parsed = part.split(";")[0].strip()
                    # parsed is <url>
                    if "page=" in parsed:
                        try:
                            page_str = parsed.split("page=")[1].split(">")[0]
                            return int(page_str)
                        except ValueError:
                            pass
        # fall back to X-Total-Count header
        total = resp.headers.get("X-Total-Count")
        data_len = len(resp.json().get("data", []))
        if total is not None and data_len:
            try:
                total = int(total)
                per_page = data_len
                # compute ceil
                return (total + per_page - 1) // per_page
            except ValueError:
                pass
    except Exception as e:
        print(f"Error determining total pages: {e}")
    # if we can't figure it out, default to 1
    return 1


async def accessible(session, base):
    try:
        resp = await session.get(base, timeout=5)
        return resp.status_code < 400
    except Exception:
        return False

async def scan_instance(session, base):
    # don't rescan the same instance
    if base in checked_instances:
        return
    can_access = await accessible(session, base)
    if not can_access:
        print(f"Instance unreachable: {base}")
        save_to_file("invalid_instances.txt", base)
        invalid_urls.add(base)
        return
    checked_instances.add(base)

    max_page = await get_total_pages(session, base)
    print(f"Total pages on {base}: {max_page}")
    # reuse a smaller semaphore per instance for page fetches
    sem = asyncio.Semaphore(20)

    async def bounded(page):
        async with sem:
            await process_page(session, base, page)

    await asyncio.gather(*(bounded(page) for page in range(1, max_page + 1)))

async def main():
    async with requests.AsyncSession() as session:
        # global concurrency across instances
        inst_sem = asyncio.Semaphore(100)

        async def bounded_instance(b):
            async with inst_sem:
                await scan_instance(session, b)

        await asyncio.gather(*(bounded_instance(b) for b in instances))

if __name__ == "__main__":
    asyncio.run(main())
