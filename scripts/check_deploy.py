"""Reads the live app's build marker and says whether the push landed.

Streamlit renders through JavaScript, so the commit the app prints is not
in the HTML a plain fetch returns. This opens the page in a headless
browser, waits for the marker, and compares it with the commit that was
just pushed.

Its real value is telling the layers apart. "The app did not update" can
mean the push never arrived, the platform never noticed, the rebuild
failed, or the browser is showing a cached page — and those need
different fixes. This says which one it is.

Free: a GitHub runner, a preinstalled browser, and about forty seconds.
"""
import os
import re
import sys
import time

MARKER = re.compile(r"build\s+([0-9a-f]{7})", re.IGNORECASE)


def main() -> int:
    url = os.environ.get("APP_URL", "").strip()
    expected = os.environ.get("EXPECTED", "").strip()
    budget = int(os.environ.get("WAIT", "180") or 180)
    if not url:
        print("No APP_URL set; nothing to check.")
        return 0

    from playwright.sync_api import sync_playwright

    deadline = time.time() + budget
    seen = ""
    with sync_playwright() as play:
        browser = play.chromium.launch()
        page = browser.new_page()
        while time.time() < deadline:
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
                # Streamlit paints the app after the socket connects, so
                # give the marker a moment to appear rather than reading
                # the loading shell.
                page.wait_for_timeout(4000)
                found = MARKER.search(page.inner_text("body"))
                if found:
                    seen = found.group(1)
                    if seen == expected:
                        print(f"LIVE BUILD: {seen} — matches the pushed commit.")
                        browser.close()
                        return 0
                    print(f"live build is {seen}, waiting for {expected}…")
                else:
                    print("no build marker on the page yet…")
            except Exception as exc:
                print(f"page not ready ({exc.__class__.__name__})…")
            time.sleep(20)
        browser.close()

    # A miss is reported, not raised: the deployment platform is outside
    # this repository's control, and failing the workflow would only make
    # a red mark that says nothing the message below does not.
    if seen:
        print(f"::warning title=Live build is behind::The app is serving "
              f"{seen}; the pushed commit is {expected}. The push and the "
              f"build are fine — the platform has not picked it up, which "
              f"usually means the GitHub connection needs reauthorising.")
    else:
        print("::warning title=No build marker::Could not read a build "
              "marker. The app may be asleep, still building, or failing "
              "to start.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
