# driver.find_element(By.XPATH, "/html/body/section[1]/div[2]/div[1]/div/div/div/div/a[2]")

# FIND ELEMENT

# find element using selenium web driver
# from selenium import webdriver
# from selenium.webdriver.common.by import By

# driver = webdriver.Chrome()

# driver.get("https://www.selenium.dev/selenium/web/web-form.html")

# title = driver.title

# driver.implicitly_wait(0.5)

# text_box = driver.find_element(by=By.NAME, value="my-text")
# submit_button = driver.find_element(by=By.CSS_SELECTOR, value="button")

# text_box.send_keys("Selenium")
# submit_button.click()

# message = driver.find_element(by=By.ID, value="message")
# text = message.text

# print(f"Title: {title}")
# print(f"Message: {text}")

# import time
# time.sleep(30)  # Keep the browser open for 30 seconds

# driver.quit()


# OPEN , SWITCH AND CLOSE A TAB

# Import module 
# from selenium import webdriver 

# # Create object 
# driver = webdriver.Chrome() 

# # Fetching the Url 
# url = "https://www.geeksforgeeks.org/"

# # New Url 
# new_url = "https://www.facebook.com/"

# # Opening first url 
# driver.get(url) 

# # Open a new window 
# driver.execute_script("window.open('');") 

# # Switch to the new window and open new URL 
# driver.switch_to.window(driver.window_handles[1]) 
# driver.get(new_url) 

# # Closing new_url tab 
# driver.close() 

# # Switching to old tab 
# driver.switch_to.window(driver.window_handles[0]) 

# import time
# time.sleep(10)  # Keep the browser open for 30 seconds

# SCROLL BAR

# from selenium import webdriver
# from selenium.webdriver import ActionChains
# from selenium.webdriver.common.by import By

# driver = webdriver.Chrome() 
# driver.get("https://selenium.dev/selenium/web/scrolling_tests/frame_with_nested_scrolling_frame_out_of_view.html")

# iframe = driver.find_element(By.TAG_NAME, "iframe")
# ActionChains(driver)\
#     .scroll_to_element(iframe)\
#     .perform()

# import time
# time.sleep(10)

# BUTTON SELENIUM

import time
# importing webdriver from selenium
from selenium import webdriver
from selenium.webdriver.common.by import By
from time import sleep

# Here Chrome  will be used
driver = webdriver.Chrome()

# URL of website
url = "https://www.geeksforgeeks.org/"

# Opening the website
driver.get(url)
sleep(2)
# Getting the button by class name
button = driver.find_element(By.XPATH, '//*[@id="comp"]/div/div/div[1]/div[1]/div[1]')

# Clicking on the button
button.click()

# Optionally, you can add a delay to see the result before closing
time.sleep(2)

# Close the browser
driver.quit()