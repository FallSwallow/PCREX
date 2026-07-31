import os
import time
import ctypes
import re
from pynput import mouse, keyboard
import win32gui
import win32ui
import win32con
import pyautogui
import cv2
import numpy as np

selected_window = {}
stop_requested = False
score_logging_enabled = False
# 模擬器內容區相對座標，不是螢幕絕對座標
SCAN_REGION = (525, 384, 917, 440)
SCAN_CENTER = (720, 412)
LOCK_REGION = (30, 235, 415, 290)
LOCK_CENTER = (222, 263)
STATUS_TEMPLATE_NAMES = {"lock.png", "unlock.png"}
LOCK_STATE_RULES = {
    "lock_confirm_threshold": 0.90,
}
MATCH_RULES = {
    "match_threshold": 0.65,
    "confident_match_threshold": 0.80,
    "front_match_threshold": 0.80,
    "back_match_threshold": 0.80,
}
EXCEPT_RULES = {
    "except_threshold": 0.70,
    "except_dominance_margin": 0.08,
    "except_same_family_margin": 0.02,
    "strict_templates": {
        "lockicon.png": 0.95,
    },
}
# 畫面按鈕座標
BUTTONS = {
    "btn_star": (777, 432),
    "btn_ok": (590, 432),
    "btn_save": (850, 492),
    "btn_again": (706, 492),
    "btn_drop": (593, 492),
    "btn_drop_double_check": (592, 475),
    "btn_again_double_check": (592, 435)
}
# 目標模式圖片模板
TARGET_TEMPLATE_PAIRS = {
    "f.png": "index_3.png",
    "m.png": "index_3.png",
    "Attack.png": "index_2%.png",
    "Magic.png": "index_2%.png",
}
MODE2_TEMPLATE_PAIRS = {
    "f.png": "index_3.png",
    "m.png": "index_3.png",
}
MODE3_TP_TEMPLATE_PAIRS = {
    "TPup.png": "index_3.png",
}
MODE4_TEMPLATE_PAIRS = {
    "f.png": "index_5.png",
    "m.png": "index_5.png",
}


# 設定緊急停止旗標，供主流程安全中斷使用。
def request_stop():
    global stop_requested
    stop_requested = True


# 回傳目前是否要輸出模板相似度詳細資訊。
def should_log_scores():
    return score_logging_enabled


# 在關鍵節點檢查是否收到緊急停止要求。
def ensure_not_stopped():
    if stop_requested:
        raise KeyboardInterrupt("緊急終止")


# 監聽全域 ESC 按鍵，作為緊急終止開關。
def on_press_emergency(key):
    if key == keyboard.Key.esc:
        request_stop()
        print("\n偵測到緊急終止按鍵 ESC，準備停止腳本...")


# 讀取模擬器內容區解析度，預設帶入剛選取視窗的外框大小。
def prompt_resolution():
    default_width = selected_window.get("window_width", 960)
    default_height = selected_window.get("window_height", 540)
    default_resolution = f"{default_width}x{default_height}"

    while True:
        raw = input(
            f"\n請輸入模擬器內容區解析度（例如 960x540，所選取視窗 {default_resolution}）: "
        ).strip().lower()
        if not raw:
            raw = default_resolution
        normalized = raw.replace(" ", "").replace("*", "x")
        if "x" not in normalized:
            print(f"格式錯誤，請使用 寬x高，例如 {default_resolution}")
            continue

        width_text, height_text = normalized.split("x", 1)
        if not width_text.isdigit() or not height_text.isdigit():
            print(f"解析度必須是數字，例如 {default_resolution}")
            continue

        width = int(width_text)
        height = int(height_text)
        if width <= 0 or height <= 0:
            print("解析度必須大於 0")
            continue

        return width, height

# 從子視窗一路往上找到最上層父視窗。
def get_top_window(hwnd):
    while True:
        parent = win32gui.GetParent(hwnd)
        if parent == 0:
            return hwnd
        hwnd = parent

# 點選任一位置後，記錄所屬最上層視窗資訊。
def on_click(x, y, button, pressed):
    if not pressed:
        return

    hwnd = win32gui.WindowFromPoint((x, y))
    hwnd = get_top_window(hwnd)

    title = win32gui.GetWindowText(hwnd)
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    window_width = right - left
    window_height = bottom - top

    print("\n已選取視窗")
    print("標題:", title)
    print("外框位置:", left, top)
    print("外框大小:", window_width, window_height)

    selected_window["hwnd"] = hwnd
    selected_window["title"] = title
    selected_window["window_left"] = left
    selected_window["window_top"] = top
    selected_window["window_width"] = window_width
    selected_window["window_height"] = window_height

    return False


# 載入指定資料夾中的模板圖片，可依名稱包含或排除。
def load_templates(template_dir="./img", exclude_names=None, include_names=None, use_color=False):
    exclude_names = {name.lower() for name in (exclude_names or [])}
    include_names = {name.lower() for name in (include_names or [])}
    templates = []
    for file_name in sorted(os.listdir(template_dir)):
        lower_name = file_name.lower()
        if not file_name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
            continue
        if include_names and lower_name not in include_names:
            continue
        if lower_name in exclude_names:
            continue

        path = os.path.join(template_dir, file_name)
        color_image = cv2.imread(path, cv2.IMREAD_COLOR)
        gray_image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if gray_image is None or color_image is None:
            print(f"略過無法讀取的模板: {path}")
            continue

        binary_image = to_binary(gray_image)

        templates.append(
            {
                "name": file_name,
                "color_image": color_image,
                "gray_image": gray_image,
                "binary_image": binary_image,
                "width": gray_image.shape[1],
                "height": gray_image.shape[0],
            }
        )

    return templates


# 載入排除用模板，例如 lockicon 或其他例外圖示。
def load_except_templates(template_dir="./img/except"):
    if not os.path.isdir(template_dir):
        return {}
    templates = load_templates(template_dir)
    return {template["name"]: template for template in templates}


# 將 except 資料夾中的模板依命名規則分成前半文字、後半數值與單圖示排除。
def classify_except_templates(except_templates):
    front_templates = {}
    back_templates = {}
    strict_templates = {}

    for name, template in except_templates.items():
        lower_name = name.lower()
        if lower_name in EXCEPT_RULES["strict_templates"]:
            strict_templates[name] = template
        elif lower_name.startswith("txt_"):
            front_templates[name] = template
        elif lower_name.startswith("index_"):
            back_templates[name] = template

    return front_templates, back_templates, strict_templates


# 載入 lock/unlock 狀態判斷所需的圖示模板。
def load_lock_state_templates(template_dir="./img"):
    if not os.path.isdir(template_dir):
        return []
    return load_templates(template_dir, include_names=STATUS_TEMPLATE_NAMES, use_color=True)


# 載入前半文字區與後半數值區的合法配對模板。
def load_target_pair_templates(template_dir="./img"):
    if not os.path.isdir(template_dir):
        return {}
    target_names = (
        set(TARGET_TEMPLATE_PAIRS.keys())
        | set(TARGET_TEMPLATE_PAIRS.values())
        | set(MODE2_TEMPLATE_PAIRS.keys())
        | set(MODE2_TEMPLATE_PAIRS.values())
        | set(MODE3_TP_TEMPLATE_PAIRS.keys())
        | set(MODE3_TP_TEMPLATE_PAIRS.values())
        | set(MODE4_TEMPLATE_PAIRS.keys())
        | set(MODE4_TEMPLATE_PAIRS.values())
    )
    templates = load_templates(template_dir, include_names=target_names)
    return {template["name"]: template for template in templates}


# 依模式回傳目前實際使用的配對規則。
def get_active_template_pairs(mode_name):
    if mode_name == "2":
        return MODE2_TEMPLATE_PAIRS
    if mode_name == "3":
        return MODE3_TP_TEMPLATE_PAIRS
    if mode_name == "4":
        return MODE4_TEMPLATE_PAIRS
    return TARGET_TEMPLATE_PAIRS

# 將內容區相對座標轉成螢幕絕對座標。
def content_to_screen(x, y):
    return selected_window["content_left"] + x, selected_window["content_top"] + y

# 將內容區內的矩形區塊轉成螢幕絕對座標矩形。
def content_box_to_screen(box):
    x1, y1, x2, y2 = box
    left, top = content_to_screen(x1, y1)
    right, bottom = content_to_screen(x2, y2)
    return left, top, right, bottom


# 直接從選取視窗擷取目前畫面，避免一般螢幕擷取抓不到模擬器內容。
def capture_window_bgr(hwnd):
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width = right - left
    height = bottom - top

    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()

    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)

    # 先嘗試 PrintWindow，失敗再退回 BitBlt
    result = 0
    try:
        result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)
    except Exception:
        result = 0

    if result != 1:
        save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)

    bmp_info = bitmap.GetInfo()
    bmp_str = bitmap.GetBitmapBits(True)
    image = np.frombuffer(bmp_str, dtype=np.uint8)
    image = image.reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))
    bgr = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

    win32gui.DeleteObject(bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    return bgr


# 擷取內容區指定範圍並轉成灰階影像。
def screenshot_content_gray(content_region=None):
    content_bgr = screenshot_content_bgr(content_region)
    if content_bgr is None or content_bgr.size == 0:
        raise RuntimeError(
            f"無法取得有效的灰階擷取影像，content_region={content_region}"
        )
    return cv2.cvtColor(content_bgr, cv2.COLOR_BGR2GRAY)


# 擷取內容區指定範圍的彩色影像。
def screenshot_content_bgr(content_region=None):
    window_bgr = capture_window_bgr(selected_window["hwnd"])
    content_offset_left = selected_window["content_left"] - selected_window["window_left"]
    content_offset_top = selected_window["content_top"] - selected_window["window_top"]
    content_offset_right = content_offset_left + selected_window["content_width"]
    content_offset_bottom = content_offset_top + selected_window["content_height"]

    window_height, window_width = window_bgr.shape[:2]
    clipped_left = max(0, min(content_offset_left, window_width))
    clipped_top = max(0, min(content_offset_top, window_height))
    clipped_right = max(0, min(content_offset_right, window_width))
    clipped_bottom = max(0, min(content_offset_bottom, window_height))

    if clipped_left >= clipped_right or clipped_top >= clipped_bottom:
        raise RuntimeError(
            "內容區裁切後為空，請確認模擬器解析度是否大於目前視窗可見範圍。"
            f" window_size=({window_width}, {window_height}),"
            f" content_offsets=({content_offset_left}, {content_offset_top}, "
            f"{content_offset_right}, {content_offset_bottom})"
        )

    content_bgr = window_bgr[
        clipped_top:clipped_bottom,
        clipped_left:clipped_right,
    ]

    if content_region is None:
        return content_bgr

    x1, y1, x2, y2 = content_region
    region_height, region_width = content_bgr.shape[:2]
    clipped_x1 = max(0, min(x1, region_width))
    clipped_y1 = max(0, min(y1, region_height))
    clipped_x2 = max(0, min(x2, region_width))
    clipped_y2 = max(0, min(y2, region_height))

    if clipped_x1 >= clipped_x2 or clipped_y1 >= clipped_y2:
        raise RuntimeError(
            "指定搜尋區域超出目前可擷取的內容區範圍。"
            f" content_region={content_region},"
            f" content_size=({region_width}, {region_height})"
        )

    return content_bgr[clipped_y1:clipped_y2, clipped_x1:clipped_x2]


# 將灰階影像轉成二值圖，供舊版辨識流程保留使用。
def to_binary(image):
    blurred = cv2.GaussianBlur(image, (3, 3), 0)
    _, binary = cv2.threshold(
        blurred,
        0,
        255,
        cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU,
    )
    return binary


# 萃取模板檔名的系列名稱，用於 attack3/attack4 這類同系判斷。
def template_family_name(template_name):
    stem = os.path.splitext(template_name)[0].lower()
    return re.sub(r"\d+$", "", stem)


# 用灰階與二值圖比對模板，回傳最佳命中結果。
def find_best_match_in_image(search_gray, search_binary, templates, log_scores=True):
    best_match = None

    for template in templates:
        tmpl_gray = template["gray_image"]
        tmpl_binary = template["binary_image"]
        if search_gray.shape[0] < tmpl_gray.shape[0] or search_gray.shape[1] < tmpl_gray.shape[1]:
            continue

        gray_result = cv2.matchTemplate(search_gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
        binary_result = cv2.matchTemplate(search_binary, tmpl_binary, cv2.TM_CCOEFF_NORMED)
        _, gray_score, _, gray_loc = cv2.minMaxLoc(gray_result)
        _, binary_score, _, binary_loc = cv2.minMaxLoc(binary_result)

        if binary_score >= gray_score:
            score = binary_score
            max_loc = binary_loc
            match_mode = "binary"
        else:
            score = gray_score
            max_loc = gray_loc
            match_mode = "gray"

        if log_scores:
            print(
                f"模板 {template['name']}: gray={gray_score:.4f}, "
                f"binary={binary_score:.4f}, use={match_mode}"
            )

        if best_match is not None and score <= best_match["score"]:
            continue

        best_match = {
            "template_name": template["name"],
            "score": score,
            "match_mode": match_mode,
            "max_loc": max_loc,
            "width": template["width"],
            "height": template["height"],
        }

    return best_match


# 用彩色圖進行模板比對，回傳最佳命中結果。
def find_best_color_match_in_image(search_bgr, templates, log_scores=True):
    best_match = None

    for template in templates:
        tmpl_color = template.get("color_image")
        if tmpl_color is None:
            continue
        if search_bgr.shape[0] < tmpl_color.shape[0] or search_bgr.shape[1] < tmpl_color.shape[1]:
            continue

        color_result = cv2.matchTemplate(search_bgr, tmpl_color, cv2.TM_CCOEFF_NORMED)
        _, color_score, _, color_loc = cv2.minMaxLoc(color_result)

        if log_scores:
            print(f"彩色模板 {template['name']}: color={color_score:.4f}")

        if best_match is not None and color_score <= best_match["score"]:
            continue

        best_match = {
            "template_name": template["name"],
            "score": color_score,
            "match_mode": "color",
            "max_loc": color_loc,
            "width": template["width"],
            "height": template["height"],
        }

    return best_match


# 回傳指定區域內各模板的彩色比對分數，供區塊級輸出使用。
def get_color_scores_in_region(content_region, templates):
    search_bgr = screenshot_content_bgr(content_region)
    scores = {}

    for template in templates:
        tmpl_color = template.get("color_image")
        if tmpl_color is None:
            scores[template["name"]] = None
            continue
        if search_bgr.shape[0] < tmpl_color.shape[0] or search_bgr.shape[1] < tmpl_color.shape[1]:
            scores[template["name"]] = None
            continue

        color_result = cv2.matchTemplate(search_bgr, tmpl_color, cv2.TM_CCOEFF_NORMED)
        _, color_score, _, _ = cv2.minMaxLoc(color_result)
        scores[template["name"]] = color_score

    return scores


# 以區塊為單位，輸出前半、後半與排除模板的完整比對準確度。
def log_quadrant_template_scores(quadrant_name, quadrant_region, templates, active_template_pairs, except_templates):
    if not should_log_scores():
        return

    sub_regions = split_region_front_back(quadrant_region)

    front_templates = [
        templates[name]
        for name in active_template_pairs.keys()
        if name in templates
    ]
    back_templates = [
        templates[name]
        for name in sorted(set(active_template_pairs.values()))
        if name in templates
    ]

    front_scores = get_color_scores_in_region(sub_regions["front"], front_templates)
    back_scores = get_color_scores_in_region(sub_regions["back"], back_templates)
    except_templates = except_templates or {}
    except_front_templates, except_back_templates, strict_except_templates = classify_except_templates(except_templates)
    except_scores = get_color_scores_in_region(quadrant_region, list(strict_except_templates.values()))

    if front_scores:
        front_text = ", ".join(
            f"{name}={score:.4f}" if score is not None else f"{name}=N/A"
            for name, score in front_scores.items()
        )
        print(f"區塊 {quadrant_name} 前半目標準確度: {front_text}")

    if back_scores:
        back_text = ", ".join(
            f"{name}={score:.4f}" if score is not None else f"{name}=N/A"
            for name, score in back_scores.items()
        )
        print(f"區塊 {quadrant_name} 後半目標準確度: {back_text}")

    if except_scores:
        except_text = ", ".join(
            f"{name}={score:.4f}" if score is not None else f"{name}=N/A"
            for name, score in except_scores.items()
        )
        print(f"區塊 {quadrant_name} 排除模板準確度: {except_text}")

    except_front_scores = get_color_scores_in_region(sub_regions["front"], list(except_front_templates.values()))
    except_back_scores = get_color_scores_in_region(sub_regions["back"], list(except_back_templates.values()))

    if except_front_scores:
        except_front_text = ", ".join(
            f"{name}={score:.4f}" if score is not None else f"{name}=N/A"
            for name, score in except_front_scores.items()
        )
        print(f"區塊 {quadrant_name} 排除前半準確度: {except_front_text}")

    if except_back_scores:
        except_back_text = ", ".join(
            f"{name}={score:.4f}" if score is not None else f"{name}=N/A"
            for name, score in except_back_scores.items()
        )
        print(f"區塊 {quadrant_name} 排除後半準確度: {except_back_text}")

    best_target_pair = None
    for front_name, back_name in active_template_pairs.items():
        front_score = front_scores.get(front_name)
        back_score = back_scores.get(back_name)
        if front_score is None or back_score is None:
            continue
        pair_score = min(front_score, back_score)
        if best_target_pair is None or pair_score > best_target_pair["pair_score"]:
            best_target_pair = {
                "front_name": front_name,
                "back_name": back_name,
                "front_score": front_score,
                "back_score": back_score,
                "pair_score": pair_score,
            }

    best_except_pair = None
    if except_front_scores and except_back_scores:
        for except_front_name, except_front_score in except_front_scores.items():
            if except_front_score is None:
                continue
            for except_back_name, except_back_score in except_back_scores.items():
                if except_back_score is None:
                    continue
                pair_score = min(except_front_score, except_back_score)
                if best_except_pair is None or pair_score > best_except_pair["pair_score"]:
                    best_except_pair = {
                        "front_name": except_front_name,
                        "back_name": except_back_name,
                        "front_score": except_front_score,
                        "back_score": except_back_score,
                        "pair_score": pair_score,
                    }

    has_valid_target_pair = (
        best_target_pair is not None
        and best_target_pair["front_score"] >= MATCH_RULES["front_match_threshold"]
        and best_target_pair["back_score"] >= MATCH_RULES["back_match_threshold"]
    )

    if has_valid_target_pair:
        print(
            f"區塊 {quadrant_name} 最有可能組合: "
            f"{best_target_pair['front_name']} + {best_target_pair['back_name']} "
            f"(front={best_target_pair['front_score']:.4f}, back={best_target_pair['back_score']:.4f})"
        )
    elif best_except_pair is not None:
        print(
            f"區塊 {quadrant_name} 最有可能組合: "
            f"{best_except_pair['front_name']} + {best_except_pair['back_name']} "
            f"(front={best_except_pair['front_score']:.4f}, back={best_except_pair['back_score']:.4f})"
        )


# 以區塊前後半做排除模板配對，回傳最佳排除命中。
def find_best_except_pair_match(quadrant_region, except_templates, threshold):
    if not except_templates:
        return None

    except_front_templates, except_back_templates, _ = classify_except_templates(except_templates)
    sub_regions = split_region_front_back(quadrant_region)
    best_match = None

    for front_name, front_template in except_front_templates.items():
        for back_name, back_template in except_back_templates.items():
            if front_template is None or back_template is None:
                continue

            front_match = find_best_template_in_region(
                sub_regions["front"],
                [front_template],
                threshold=threshold,
                log_scores=False,
            )
            if front_match is None:
                continue

            back_match = find_best_template_in_region(
                sub_regions["back"],
                [back_template],
                threshold=threshold,
                log_scores=False,
            )
            if back_match is None:
                continue

            score = min(front_match["score"], back_match["score"])
            if best_match is not None and score <= best_match["score"]:
                continue

            best_match = {
                "template_name": f"{front_name} + {back_name}",
                "label_template": front_name,
                "value_template": back_name,
                "score": score,
                "match_mode": f"{front_match['match_mode']}+{back_match['match_mode']}",
            }

    return best_match


# 目前以彩色辨識為主，灰階/二值化流程保留為備用。
def find_best_template_match(search_bgr, search_gray, search_binary, templates, log_scores=True):
    # 先暫時只使用彩色辨識，灰階/二值化流程保留供後續比較
    # gray_match = find_best_match_in_image(search_gray, search_binary, templates, log_scores=log_scores)
    color_match = find_best_color_match_in_image(search_bgr, templates, log_scores=log_scores)
    # if gray_match is None:
    #     return color_match
    # if color_match is None:
    #     return gray_match
    # if color_match["score"] > gray_match["score"]:
    #     return color_match
    # return gray_match
    return color_match


# 依指定中心點將矩形區域切成左上、左下、右上、右下四格。
def split_region_into_quadrants(region, center):
    x1, y1, x2, y2 = region
    mid_x, mid_y = center
    return {
        "left_top": (x1, y1, mid_x, mid_y),
        "left_bottom": (x1, mid_y, mid_x, y2),
        "right_top": (mid_x, y1, x2, mid_y),
        "right_bottom": (mid_x, mid_y, x2, y2),
    }


# 將單一屬性區塊切成前半文字區與後半數值區。
def split_region_front_back(region):
    x1, y1, x2, y2 = region
    mid_x = x1 + (x2 - x1) // 2
    return {
        "front": (x1, y1, mid_x, y2),
        "back": (mid_x, y1, x2, y2),
    }


# 在指定區域內找出最佳模板命中，並附上螢幕座標資訊。
def find_best_template_in_region(
    content_region,
    templates,
    threshold=None,
    run_index=None,
    log_scores=True,
):
    if threshold is None:
        threshold = MATCH_RULES["match_threshold"]
    screen_region = content_box_to_screen(content_region)
    search_bgr = screenshot_content_bgr(content_region)
    if search_bgr is None or search_bgr.size == 0:
        return None
    if log_scores and should_log_scores():
        print(f"目前擷取區域: {content_region}, 螢幕區域: {screen_region}")
    search_gray = cv2.cvtColor(search_bgr, cv2.COLOR_BGR2GRAY)
    search_binary = to_binary(search_gray)

    best_match = find_best_template_match(
        search_bgr,
        search_gray,
        search_binary,
        templates,
        log_scores=log_scores,
    )

    if best_match is None or best_match["score"] < threshold:
        return None

    match_left = screen_region[0] + best_match["max_loc"][0]
    match_top = screen_region[1] + best_match["max_loc"][1]
    best_match["screen_box"] = (
        match_left,
        match_top,
        match_left + best_match["width"],
        match_top + best_match["height"],
    )
    best_match["match_click_point"] = (
        match_left + best_match["width"] // 2,
        match_top + best_match["height"] // 2,
    )

    return best_match


# 對單一分區做完整判斷：前後半配對、排除模板過濾與信心門檻檢查。
def evaluate_quadrant_match(
    quadrant_name,
    quadrant_region,
    templates,
    active_template_pairs,
    except_templates=None,
    threshold=None,
    run_index=None,
):
    if threshold is None:
        threshold = MATCH_RULES["match_threshold"]
    log_quadrant_template_scores(
        quadrant_name,
        quadrant_region,
        templates,
        active_template_pairs,
        except_templates,
    )
    sub_regions = split_region_front_back(quadrant_region)
    best_pair_match = None

    for front_name, back_name in active_template_pairs.items():
        front_template = templates.get(front_name)
        back_template = templates.get(back_name)
        if front_template is None or back_template is None:
            continue

        front_match = find_best_template_in_region(
            sub_regions["front"],
            [front_template],
            threshold=threshold,
            run_index=run_index,
            log_scores=False,
        )
        if front_match is None:
            if should_log_scores():
                print(f"區塊 {quadrant_name}: 配對 {front_name} + {back_name} (front=未命中)")
            continue

        back_match = find_best_template_in_region(
            sub_regions["back"],
            [back_template],
            threshold=threshold,
            run_index=run_index,
            log_scores=False,
        )
        if back_match is None:
            if should_log_scores():
                print(
                    f"區塊 {quadrant_name}: 配對 {front_name} + {back_name} "
                    f"(front={front_match['score']:.4f}, back=未命中)"
                )
            continue
        if should_log_scores():
            print(
                f"區塊 {quadrant_name}: 配對 {front_name} + {back_name} "
                f"(front={front_match['score']:.4f}, back={back_match['score']:.4f})"
            )

        if front_match["score"] < MATCH_RULES["front_match_threshold"]:
            if should_log_scores():
                print(
                    f"區塊 {quadrant_name}: 前半 {front_name} "
                    f"分數 {front_match['score']:.4f} 未高於 {MATCH_RULES['front_match_threshold']:.2f}"
                )
            continue
        if back_match["score"] < MATCH_RULES["back_match_threshold"]:
            if should_log_scores():
                print(
                    f"區塊 {quadrant_name}: 後半 {back_name} "
                    f"分數 {back_match['score']:.4f} 未高於 {MATCH_RULES['back_match_threshold']:.2f}"
                )
            continue
        pair_score = min(front_match["score"], back_match["score"])

        if best_pair_match is not None and pair_score <= best_pair_match["score"]:
            continue

        best_pair_match = {
            "template_name": f"{front_name} + {back_name}",
            "label_template": front_name,
            "value_template": back_name,
            "score": pair_score,
            "match_mode": f"{front_match['match_mode']}+{back_match['match_mode']}",
            "screen_box": (
                min(front_match["screen_box"][0], back_match["screen_box"][0]),
                min(front_match["screen_box"][1], back_match["screen_box"][1]),
                max(front_match["screen_box"][2], back_match["screen_box"][2]),
                max(front_match["screen_box"][3], back_match["screen_box"][3]),
            ),
            "front_score": front_match["score"],
            "back_score": back_match["score"],
        }

    if best_pair_match is None:
        if should_log_scores():
            print(f"區塊 {quadrant_name}: 未找到合法配對目標")
        return None

    match = best_pair_match

    except_match = contains_except_icon(quadrant_region, except_templates or [])
    if except_match is not None:
        strict_threshold = EXCEPT_RULES["strict_templates"].get(
            except_match["template_name"].lower()
        )
        if strict_threshold is not None and except_match["score"] >= strict_threshold:
            if should_log_scores():
                print(
                    f"區塊 {quadrant_name}: 排除圖示 {except_match['template_name']} "
                    f"分數 {except_match['score']:.4f} 高於 {strict_threshold:.2f}，維持排除"
                )
            return None
        same_family = (
            template_family_name(except_match["template_name"])
            == template_family_name(match["template_name"])
        )
        if except_match["score"] >= match["score"] + EXCEPT_RULES["except_dominance_margin"]:
            if should_log_scores():
                print(
                    f"區塊 {quadrant_name}: 因出現排除圖示 {except_match['template_name']} "
                    f"(score={except_match['score']:.4f}) 而忽略"
                )
            return None
        if (
            same_family
            and except_match["score"]
            >= match["score"] - EXCEPT_RULES["except_same_family_margin"]
        ):
            if should_log_scores():
                print(
                    f"區塊 {quadrant_name}: 同系列排除圖示 {except_match['template_name']} "
                    f"與主模板 {match['template_name']} 分數過近，優先忽略"
                )
            return None
        if should_log_scores():
            print(
                f"區塊 {quadrant_name}: 排除圖示 {except_match['template_name']} "
                f"分數接近但未超過主模板，保留主模板 {match['template_name']}"
            )

    match["quadrant"] = quadrant_name
    match["content_region"] = quadrant_region
    if match["score"] < MATCH_RULES["confident_match_threshold"]:
        if should_log_scores():
            print(
                f"區塊 {quadrant_name}: 主模板 {match['template_name']} "
                f"分數 {match['score']:.4f} 未高於 {MATCH_RULES['confident_match_threshold']:.2f}，先視為誤判"
            )
        return None
    if should_log_scores():
        print(
            f"區塊 {quadrant_name}: 找到 {match['template_name']} "
            f"(score={match['score']:.4f}, front={match['front_score']:.4f}, "
            f"back={match['back_score']:.4f}, mode={match['match_mode']})"
        )
    return match


# 在四個分區中搜尋所有有效命中，可略過已鎖定分區。
def find_matches_in_quadrants(
    scan_region,
    scan_center,
    templates,
    active_template_pairs,
    except_templates=None,
    threshold=None,
    run_index=None,
    skipped_quadrants=None,
):
    if threshold is None:
        threshold = MATCH_RULES["match_threshold"]
    quadrants = split_region_into_quadrants(scan_region, scan_center)
    skipped_quadrants = skipped_quadrants or set()
    matches = []

    for quadrant_name, quadrant_region in quadrants.items():
        if quadrant_name in skipped_quadrants:
            if should_log_scores():
                print(f"區塊 {quadrant_name}: 目前為 lock，跳過搜尋")
            continue
        match = evaluate_quadrant_match(
            quadrant_name,
            quadrant_region,
            templates,
            active_template_pairs,
            except_templates=except_templates,
            threshold=threshold,
            run_index=run_index,
        )
        if match is not None:
            matches.append(match)

    return matches


# 檢查某區域是否出現排除模板，供主目標過濾使用。
def contains_except_icon(content_region, except_templates, threshold=None):
    if threshold is None:
        threshold = EXCEPT_RULES["except_threshold"]
    if not except_templates:
        return None

    _, _, strict_templates = classify_except_templates(except_templates)
    strict_templates = list(strict_templates.values())
    strict_match = None
    if strict_templates:
        search_bgr = screenshot_content_bgr(content_region)
        search_gray = screenshot_content_gray(content_region)
        search_binary = to_binary(search_gray)
        strict_match = find_best_template_match(
            search_bgr,
            search_gray,
            search_binary,
            strict_templates,
            log_scores=False,
        )
        if strict_match is not None and strict_match["score"] < threshold:
            strict_match = None

    pair_match = find_best_except_pair_match(content_region, except_templates, threshold)

    if strict_match is None:
        return pair_match
    if pair_match is None:
        return strict_match
    if pair_match["score"] > strict_match["score"]:
        return pair_match
    return strict_match


# 依按鈕名稱取得對應的螢幕絕對座標。
def get_button_click(button_name):
    content_point = BUTTONS.get(button_name)
    if content_point is None:
        return None
    return content_to_screen(content_point[0], content_point[1])


# 一次建立所有按鈕的螢幕絕對座標表。
def get_all_button_clicks():
    return {
        button_name: content_to_screen(*content_point)
        for button_name, content_point in BUTTONS.items()
    }


# 取得四個分區各自中心點，供上鎖點擊使用。
def get_quadrant_click_points(region, center):
    quadrants = split_region_into_quadrants(region, center)
    points = {}
    for quadrant_name, quadrant_region in quadrants.items():
        x1, y1, x2, y2 = quadrant_region
        points[quadrant_name] = content_to_screen((x1 + x2) // 2, (y1 + y2) // 2)
    return points


# 從多個命中結果中挑出分數最高的一個。
def get_best_match(matches):
    if not matches:
        return None
    return max(matches, key=lambda item: item["score"])


# 只檢查區塊前半是否出現目標文字模板，供三鎖狀態提前停止。
def find_front_template_in_region(content_region, templates, active_template_pairs, threshold=None):
    if threshold is None:
        threshold = MATCH_RULES["front_match_threshold"]

    sub_regions = split_region_front_back(content_region)
    best_match = None
    for front_name in active_template_pairs.keys():
        front_template = templates.get(front_name)
        if front_template is None:
            continue

        front_match = find_best_template_in_region(
            sub_regions["front"],
            [front_template],
            threshold=threshold,
        )
        if front_match is None:
            continue
        if front_match["score"] < threshold:
            continue

        if best_match is None or front_match["score"] > best_match["score"]:
            best_match = {
                "template_name": front_name,
                "score": front_match["score"],
                "match_mode": front_match["match_mode"],
            }

    return best_match


# 在三鎖情況下，只檢查唯一未鎖分區的前半是否已出現目標文字模板。
def detect_three_lock_front_match(scan_region, scan_center, templates, locked_quadrants, active_template_pairs):
    if len(locked_quadrants) != 3:
        return None

    quadrants = split_region_into_quadrants(scan_region, scan_center)
    remaining_quadrants = [
        quadrant_name
        for quadrant_name in quadrants.keys()
        if quadrant_name not in locked_quadrants
    ]
    if not remaining_quadrants:
        return None

    remaining_quadrant = remaining_quadrants[0]
    remaining_region = quadrants[remaining_quadrant]
    front_only_match = find_front_template_in_region(
        remaining_region,
        templates,
        active_template_pairs,
        threshold=MATCH_RULES["front_match_threshold"],
    )
    if front_only_match is None:
        return None

    front_only_match["quadrant"] = remaining_quadrant
    return front_only_match


# 以彩色 lock 模板判斷四個鎖定區塊目前是否已上鎖。
def detect_lock_states(lock_region, lock_center, lock_state_templates):
    quadrants = split_region_into_quadrants(lock_region, lock_center)
    states = {}
    lock_templates = [
        template for template in lock_state_templates
        if template["name"].lower() == "lock.png"
    ]
    for quadrant_name, quadrant_region in quadrants.items():
        search_bgr = screenshot_content_bgr(quadrant_region)
        lock_match = find_best_color_match_in_image(search_bgr, lock_templates, log_scores=False)
        lock_score = lock_match["score"] if lock_match is not None else -1.0

        if lock_score >= LOCK_STATE_RULES["lock_confirm_threshold"]:
            states[quadrant_name] = "lock"
        else:
            states[quadrant_name] = "unlock"

    return states

#main function
if __name__ == "__main__":
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

    emergency_listener = keyboard.Listener(on_press=on_press_emergency)
    emergency_listener.start()

    print("請用滑鼠點一下你要綁定的視窗...")

    with mouse.Listener(on_click=on_click) as listener:
        listener.join()

    content_width, content_height = prompt_resolution()
    content_left = selected_window["window_left"]
    content_bottom = selected_window["window_top"] + selected_window["window_height"]
    content_top = content_bottom - content_height
    content_right = content_left + content_width

    selected_window["content_left"] = content_left
    selected_window["content_top"] = content_top
    selected_window["content_right"] = content_right
    selected_window["content_bottom"] = content_bottom
    selected_window["content_width"] = content_width
    selected_window["content_height"] = content_height

    print("\n內容區初始化完成")

    if content_width > selected_window["window_width"] or content_height > selected_window["window_height"]:
        print("警告: 你輸入的解析度大於目前外框尺寸，請確認是否為正確模擬器解析度或視窗縮放狀態。")

    templates = load_target_pair_templates("./img")
    except_templates = load_except_templates("./img/except")
    lock_state_templates = load_lock_state_templates("./img")

    if not templates:
        print("警告: ./img/ 沒有可用模板圖片。")
    else:
        print("已載入配對模板:", ", ".join(sorted(templates.keys())))
    if except_templates:
        print("已載入排除模板:", ", ".join(sorted(except_templates.keys())))
    if lock_state_templates:
        print("已載入鎖定模板:", ", ".join(template["name"] for template in lock_state_templates))
    
    while True:
        mode_input = input("請選擇模式 (1=一般, 2=貫通, 3=TP, 4=貫通5): ").strip()
        if mode_input in {"1", "2", "3", "4"}:
            break
        print("無效選項，請輸入 1、2、3 或 4。")

    current_mode = mode_input
    active_template_pairs = get_active_template_pairs(current_mode)
    mode_labels = {"1": "一般", "2": "貫通", "3": "TP", "4": "貫通5"}
    print("目前模式:", f"mode {current_mode} ({mode_labels.get(current_mode, '未知')})")
    print(
        "目前配對:",
        ", ".join(f"{front} + {back}" for front, back in active_template_pairs.items())
    )
    score_logging_input = input("是否輸出比對相似度？(y/n，預設n): ").strip().lower()
    score_logging_enabled = score_logging_input == "y"
    
    doublecheck = input("是否開啟結果二次確定？(y/n):")
    runTimes = input("Run Time:")
    input("設定完成回到練成畫面，按Enter開始腳本(ESC中斷)...")
    persistent_locked_quadrants = set()

    try:
        for run in range(int(runTimes)):
            ensure_not_stopped()
            buttons = get_all_button_clicks()
            stop_for_manual_review = False
            lock_states = detect_lock_states(LOCK_REGION, LOCK_CENTER, lock_state_templates)
            current_locked_quadrants = {
                quadrant_name for quadrant_name, state in lock_states.items() if state == "lock"
            }
            persistent_locked_quadrants |= current_locked_quadrants
            locked_quadrants = set(persistent_locked_quadrants)
            if locked_quadrants:
                print("目前已上鎖區域:", ", ".join(sorted(locked_quadrants)))
            if len(locked_quadrants) == 4:
                print("LOCK_REGION 四個區塊皆為 lock，工作完成，停止迴圈。")
                break
            if stop_for_manual_review:
                break
            
            #開始練成
            time.sleep(1)  # 根據遊戲反應時間
            ensure_not_stopped()
            if run == 0 or next_click == buttons["btn_save"]:
                pyautogui.click(buttons["btn_star"])
                time.sleep(1)  # 根據遊戲反應時間
                ensure_not_stopped()
                pyautogui.click(buttons["btn_ok"])
                time.sleep(1)  # 根據遊戲反應時間
            ensure_not_stopped() # 跳過動畫
            pyautogui.click(buttons["btn_ok"])
            pyautogui.click(buttons["btn_ok"])
            time.sleep(1.5)  
            ensure_not_stopped()
            if len(locked_quadrants) == 3:
                front_only_match = detect_three_lock_front_match(
                    SCAN_REGION,
                    SCAN_CENTER,
                    templates,
                    locked_quadrants,
                    active_template_pairs,
                )
                if front_only_match is not None:
                    print(
                        f"剩餘區塊 {front_only_match['quadrant']} 前半已出現目標 "
                        f"{front_only_match['template_name']} "
                        f"(score={front_only_match['score']:.4f}, "
                        f"threshold={MATCH_RULES['front_match_threshold']:.2f})，交由使用者確認後續行為。"
                    )
                    stop_for_manual_review = True
                    break
            #判斷是否出現需要的詞條
            quadrant_matches = find_matches_in_quadrants(
                SCAN_REGION,
                SCAN_CENTER,
                templates,
                active_template_pairs,
                except_templates=except_templates,
                threshold=MATCH_RULES["match_threshold"],
                run_index=run + 1,
                skipped_quadrants=locked_quadrants,
            ) if templates else []
            match = get_best_match(quadrant_matches)
            next_click = None
            if match is None:
                # print(f"第 {run + 1} 次: 指定區域內沒有找到符合模板的內容，請查看 debug 資料夾中的 scan 圖")
                print(f"第 {run + 1} 次: 指定區域內沒有找到符合模板的內容")
                if run + 1 < int(runTimes):
                    next_click = buttons["btn_again"]
                else:
                    next_click = buttons["btn_drop"]
            else:
                print(
                    f"第 {run + 1} 次: 在 {match['quadrant']} 找到 {match['template_name']} "
                    f"(score={match['score']:.4f}, mode={match['match_mode']}) at {match['screen_box']}"
                )
                next_click = buttons["btn_save"]
                
            #結果確認 
            if next_click is None:
                print("找不到 btn_save 的按鈕座標，請確認 BUTTONS 設定")
            else:
                # print("下一步點擊位置:", next_click)
                ensure_not_stopped()
                pyautogui.click(next_click)
                time.sleep(1)  # 根據遊戲反應時間
                
            if doublecheck.strip().lower() == "y":
                ensure_not_stopped()
                if next_click == buttons["btn_again"]:
                    pyautogui.click(buttons["btn_again_double_check"])
                elif next_click == buttons["btn_drop"] or next_click == buttons["btn_save"]:
                    pyautogui.click(buttons["btn_drop_double_check"])
            time.sleep(1)  # 根據遊戲反應時間
            ensure_not_stopped()
            
            #結果上鎖
            if match is not None:
                time.sleep(1)
                lock_points = get_quadrant_click_points(LOCK_REGION, LOCK_CENTER)
                for quadrant_name in [item["quadrant"] for item in quadrant_matches]:
                    if quadrant_name in locked_quadrants:
                        continue
                    lock_point = lock_points.get(quadrant_name)
                    if lock_point is None:
                        continue
                    print(f"上鎖區域 {quadrant_name}: {lock_point}")
                    ensure_not_stopped()
                    pyautogui.click(lock_point)
                    time.sleep(0.3)
    except KeyboardInterrupt:
        print("腳本已緊急終止。")
    finally:
        emergency_listener.stop()
        

        
        
        
        
        
        
