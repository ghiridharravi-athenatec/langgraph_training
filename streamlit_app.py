from playwright.sync_api import sync_playwright

def login_and_navigate():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=300)  # slow_mo helps you watch each step
        context = browser.new_context()
        page = context.new_page()

        page.goto("https://ociservices.gov.in/onlineOCI/login")

        print("Please manually enter email, password, and captcha, then click Login.")
        print("Press Resume in the Inspector once you're logged in.")
        page.pause()

        page.wait_for_load_state("networkidle")
        print("Logged in. Current URL:", page.url)

        # Step 1: Click "Online Registration"
        page.click("text=Online Registration")
        page.wait_for_load_state("networkidle")

        # Step 2: Click "New OCI Registration"
        page.click("text=New OCI Registration")
        page.wait_for_load_state("networkidle")

        # Step 3: Click "Indian Origin Applicant"
        page.click("text=Indian Origin Applicant")
        page.wait_for_load_state("networkidle")

        # Step 4: Click "Apply Online"
        page.click("text=Apply Online")
        page.wait_for_load_state("networkidle")

        # Step 5: Check "I have read the instructions" checkbox
        # Trying label text first; if it's an actual <input type=checkbox>, this locator finds
        # the checkbox associated with nearby text. Adjust selector if it doesn't match.
        page.get_by_text("I have read the instructions").locator("xpath=preceding::input[@type='checkbox'][1]").check()
        # Fallback if the above doesn't work — uncomment and use instead:
        # page.check("input[type='checkbox']")

        # Step 6: Click "Proceed to OCI Registration"
        page.click("text=Proceed to OCI Registration")
        page.wait_for_load_state("networkidle")

        print("Reached the OCI Registration form. Current URL:", page.url)

        # Pause here so you can see the form and we can figure out the next fields together
        page.pause()

        return browser, context, page

if __name__ == "__main__":
    browser, context, page = login_and_navigate()
    input("Press Enter in this terminal to close the browser...")
    browser.close()