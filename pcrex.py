#公主連結刷EX裝詞條

import os
import pyautogui
import cv2
import numpy as np
from PIL import ImageGrab
import time
from pynput.mouse import Listener

# 目標圖片資料夾位置
TEMPLATE_DIR = "./img"
TEMPLATE_PATHS = [
    os.path.join(TEMPLATE_DIR, fname)
    for fname in os.listdir(TEMPLATE_DIR)
    if fname.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp'))
]

TEMPLATE_IMAGES = [cv2.adaptiveThreshold(cv2.imread(path, cv2.IMREAD_GRAYSCALE), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY,5,1) for path in TEMPLATE_PATHS]
# TEMPLATE_IMAGES = [cv2.imread(path, cv2.IMREAD_GRAYSCALE) for path in TEMPLATE_PATHS]
lock_icon = cv2.imread('except/lockicon.png', cv2.IMREAD_GRAYSCALE)
lock_icon_binary = cv2.adaptiveThreshold(lock_icon, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY,3,0)

# === 幫助函式 ===

# 取得當前座標回傳(x,y)
def get_mouse_position_click(msg="請點擊滑鼠左鍵來設定座標..."):
    print(msg)
    pos = []

    def on_click(x, y, button, pressed):
        if pressed:
            pos.append((x, y))
            return False  # Stop listener

    with Listener(on_click=on_click) as listener:
        listener.join()
    print(f"座標：{pos[0]}")
    return pos[0]

def get_mouse_position(msg="請移到指定位置並按下 Enter"):
    input(msg)
    x, y = pyautogui.position()
    print(f"座標：({x}, {y})")
    return x, y
#取得當前座標回傳x, y
def get_mouse(msg="請將滑鼠移到指定位置並按 Enter"):
    input(msg)
    return pyautogui.position()

def crop_img(img, box):  # box: (x1, y1, x2, y2)
    return img[box[1]:box[3], box[0]:box[2]]

# 畫面黑白截圖
def screenshot_area(region):
    # region: (x1, y1, x2, y2)
    # img = ImageGrab.grab(bbox=region)
    img = cv2.cvtColor(np.array(ImageGrab.grab(bbox=region)), cv2.COLOR_BGR2GRAY)
    img_binary = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY,5,2)
    return img_binary

# 檢查屬性是否上鎖
def contains_lock_icon(img, lock_icon, threshold=0.58):
    # resize 可視情況調整，通常 icon 模板都會比整張圖小
    res = cv2.matchTemplate(img, lock_icon, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
    # print("lock_min_val:", min_val)
    # print("lock_max_val:", max_val)
    if min_val<-0.55:
        return False
    return max_val <= threshold

#比對兩個區域內容相似度
def images_are_different(img1, img2, threshold=0.95):
    if img1.shape != img2.shape:
        img2 = cv2.resize(img2, (img1.shape[1], img1.shape[0]))  # (寬,高)
    diff = cv2.absdiff(img1, img2)
    non_zero = np.count_nonzero(diff)
    size = img1.shape[1]*img1.shape[0]
    return non_zero/size > threshold  # threshold根據測試調整

# 比對目標是否出現
def match_any_template(img, templates, threshold=0.50):
    for idx, tmpl in enumerate(templates):
        if img.shape[0] < tmpl.shape[0] or img.shape[1] < tmpl.shape[1]:
            print("size error")
            continue
        res = cv2.matchTemplate(img, tmpl, cv2.TM_CCOEFF_NORMED)
        min_val, max_val, _, _ = cv2.minMaxLoc(res)
        print("min_val:", min_val)
        print("max_val:", max_val)
        print(f"偵測到：{os.path.basename(TEMPLATE_PATHS[idx])}")
        if max_val >= threshold:
            return True, idx
    return False, None

# === 主程式 ===
if __name__ == "__main__":
    print("請將滑鼠移到模擬器左上角，按Enter")
    sx, sy = get_mouse_position_click()
    print("請將滑鼠移到模擬器右下角，按Enter")
    ex, ey = get_mouse_position_click()
    
    img_w, img_h = 737, 416
    # img_w, img_h = 960, 540
    rx = (ex - sx) / img_w
    ry = (ey - sy) / img_h
    # 用戶手動執行一次記錄按鈕位置
    print("用戶手動執行一次記錄按鈕位置")
    # print("請定位\"練成\"按鈕位置")
    # 590, 335
    btn_star = (int(sx + 590 * rx), int(sy + 335 * ry))
    # print("請定位\"OK\"按鈕位置")
    # 450, 333
    btn_ok = (int(sx + 450 * rx), int(sy + 333 * ry))
    # print("請定位\"捨棄\"按鈕位置")
    # 563, 375
    btn_drop = (int(sx + 563 * rx), int(sy + 375 * ry))
    # print("請定位\"確定捨棄\"按鈕位置")
    # print("tip.如果不用再次確定 設定在不影響的空白處")
    # 454 368
    btn_dropconf = (int(sx + 454 * rx), int(sy + 368 * ry))
    
    # 左下格子
    l_boxes = [
        (int(sx+30*rx), int(sy+298*ry), int(sx+185*rx), int(sy+322*ry)),
        (int(sx+180*rx), int(sy+298*ry), int(sx+328*rx), int(sy+322*ry)),
        (int(sx+30*rx), int(sy+316*ry), int(sx+185*rx), int(sy+340*ry)),
        (int(sx+180*rx), int(sy+316*ry), int(sx+328*rx), int(sy+340*ry)),
    ]
    # 右下格子
    r_boxes = [
        (int(sx+403*rx), int(sy+298*ry), int(sx+558*rx), int(sy+322*ry)),
        (int(sx+550*rx), int(sy+298*ry), int(sx+700*rx), int(sy+322*ry)),
        (int(sx+403*rx), int(sy+316*ry), int(sx+558*rx), int(sy+340*ry)),
        (int(sx+550*rx), int(sy+316*ry), int(sx+700*rx), int(sy+340*ry)),
    ]
    
    # =========================================
    # 開始練成
    # =========================================
    runTimes = input("Run Time:")
    input("設定完成回到練成畫面，按Enter開始腳本...")
    
    for run in range(int(runTimes)):
        print("執行次數:", run+1)
        pyautogui.click(btn_star)
        time.sleep(1)  # 根據遊戲反應時間
        pyautogui.click(btn_ok)
        time.sleep(1)  # 根據遊戲反應時間
        pyautogui.click(sx, sy)
        time.sleep(2)  # 跳過動畫
        
        img = screenshot_area((sx, sy, ex, ey))

        # 依次擷取左下四格與右下四格
        l_imgs = [screenshot_area(box) for box in l_boxes]
        r_imgs = [screenshot_area(box) for box in r_boxes]

        # 開始比對 (直接比像素，或用 OCR)
        found = False
        idx = 0
        for i in range(4):
            # cv2.imshow("L", l_imgs[i])
            # cv2.imshow("R", r_imgs[i])
            
            print(f"右下格子{i+1}：", end='')
            if contains_lock_icon(l_imgs[i], lock_icon):
                print("lock_pass")
                continue
            # 檢查目標是否出現
            try:
                # print("L")
                # match_any_template(l_imgs[i], TEMPLATE_IMAGES)
                # print("R")
                found, idx = match_any_template(r_imgs[i], TEMPLATE_IMAGES)
                if found :
                    print("出現目標")
                    # break
            except Exception as e:
                print("辨識失敗：", e)
        # for idx, tmpl in enumerate(TEMPLATE_IMAGES):
        #     cv2.imshow("1", tmpl)
        #     cv2.waitKey()
        # cv2.waitKey()
        if found :
            break
        
        time.sleep(3)  # 根據遊戲反應時間
        pyautogui.click(btn_drop)
        time.sleep(1)  # 根據遊戲反應時間
        pyautogui.click(btn_dropconf)
        time.sleep(2)  # 根據遊戲反應時間
