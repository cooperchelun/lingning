#pip install google-genai
from google import genai

from google.genai import types

#from PIL import Image
#import numpy as np, easyocr

import requests
from bs4 import BeautifulSoup

from flask import Flask, render_template, request, make_response, jsonify
from datetime import datetime
import random

import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

# 判斷是在 Vercel 還是本地
if os.path.exists('serviceAccountKey.json'):
    # 本地環境：讀取檔案
    cred = credentials.Certificate('serviceAccountKey.json')
else:
    # 雲端環境：從環境變數讀取 JSON 字串
    firebase_config = os.getenv('FIREBASE_CONFIG')
    cred_dict = json.loads(firebase_config)
    cred = credentials.Certificate(cred_dict)

firebase_admin.initialize_app(cred)


app = Flask(__name__)

client = genai.Client()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/messenger")
def messenger():
    return render_template("messenger.html")

@app.route("/AI")
def AI():
    # 每次使用者拜訪該路徑時，直接使用全域的 client 呼叫模型
    response = client.models.generate_content(
        model='gemini-3.1-flash-lite',
        contents='我想查詢靜宜大學資管系的評價？',
    )
    
    # 回傳生成的文字
    return response.text


@app.route('/ask', methods=['GET', 'POST']) 
def ask():
    if request.method == "POST":
        user_prompt = request.form.get('prompt', '')
        if not user_prompt:
            return "請輸入內容", 400
        try:
            response = client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=user_prompt,
            )
            return response.text
        except Exception as e:
            return f"發生錯誤: {str(e)}", 500

    else:    
        # 當使用者直接打開網頁 (GET) 時，顯示輸入框畫面
        return render_template("ask.html")



@app.route("/message")
def message():
    return render_template("message.html")


@app.route("/webdemo")
def webdemo():
    return render_template("webdemo.html")


@app.route("/demo")
def demo():
    return render_template("demo.html")

@app.route("/webhook", methods=["POST"])
def webhook():
    # build a request object
    req = request.get_json(force=True)
    # fetch queryResult from json
    action =  req["queryResult"]["action"]
    #msg =  req["queryResult"]["queryText"]
    #info = "我是楊子青設計的電影聊天機器人, 動作：" + action + "； 查詢內容：" + msg
    if (action == "rateChoice"):
        rate =  req["queryResult"]["parameters"]["rate"]
        info = "我是楊子青設計的電影聊天機器人,您選擇的電影分級是：" + rate + "，相關電影：\n"

        db = firestore.client()
        collection_ref = db.collection("本週新片含分級")
        docs = collection_ref.get()
        result = ""
        for doc in docs:
            dict = doc.to_dict()
            if rate in dict["rate"]:
                result += "片名：" + dict["title"] + ";\n"
                result += "連結：" + dict["hyperlink"] + "\n\n"

        info += result


    elif (action == "input.unknown"):
        # 1. 取得使用者在 Dialogflow 輸入的原始文字
        user_query = req["queryResult"]["queryText"]
        
        # 2. 啟動深度爬蟲：直接抓取攻略網站的內文數據
        direct_data = ""
        try:
            # 使用特玩網的內部搜尋，直接鎖定原神角色數據
            search_url = f"http://www.te5.com/index.php?m=search&c=index&a=init&typeid=1&q=原神+{user_query}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
            
            search_res = requests.get(search_url, headers=headers, timeout=5)
            if search_res.status_code == 200:
                search_soup = BeautifulSoup(search_res.text, "html.parser")
                # 尋找第一個搜尋結果的精準文章連結
                first_link = search_soup.find("div", class_="search-list")
                if first_link and first_link.find("a"):
                    target_url = first_link.find("a").get("href")
                    
                    # 【關鍵步驟】直接點進去該篇 6.X 攻略文章爬取整頁直接數據
                    page_res = requests.get(target_url, headers=headers, timeout=5)
                    if page_res.status_code == 200:
                        page_soup = BeautifulSoup(page_res.text, "html.parser")
                        # 抓取文章主體內容（通常包含聖遺物數據、數值推薦、新版本配隊）
                        content_div = page_soup.find("div", class_="content")
                        if content_div:
                            # 唯獨抓取前 1500 個字（最精準的角色面板與數據核心）
                            direct_data = content_div.text.strip()[:1500]
        except Exception as crawl_err:
            print(f"深度直接數據爬蟲失敗: {crawl_err}")
    
        # 3. 備用防線：如果特玩網沒抓到，改用 Google 即時生鮮摘要補字
        if not direct_data:
            try:
                google_url = f"https://www.google.com/search?q=原神+{user_query}+最新攻略"
                g_res = requests.get(google_url, headers=headers, timeout=4)
                if g_res.status_code == 200:
                    g_soup = BeautifulSoup(g_res.text, "html.parser")
                    snippets = g_soup.find_all("div", class_="VwiC3b")
                    direct_data = "\n".join([s.text for s in snippets[:3]])
            except:
                pass
    
        # 4. 設定系統指令，強迫 Gemini 必須根據爬到的「第一手生鮮數據」來回答
        instruction_text = (
            "你是一位專注於《原神》(Genshin Impact) 的專業智慧助理。\n"
            "目前遊戲已更新至 6.X 以上的全新版本。請注意，使用者的提問必須與原神相關，若無關請禮貌拒絕。\n\n"
            "【核心任務】\n"
            "請根據下方透過網絡爬蟲『直接從攻略網站抓取的最新一手的生鮮數據』進行分析與整理，"
            "精準回答使用者提問的 6.X 版本最新角色數據、天賦、聖遺物與配隊。不要瞎掰，完全以爬蟲數據為準！\n\n"
            "【爬蟲抓取的最新一手生鮮數據】：\n"
            f"{direct_data if direct_data else '（未能抓取到即時網頁，請嘗試用你已知的最新原神知識回答）'}\n\n"
            "【必填參考連結】：\n"
            "- 巴哈姆特原神哈啦板: https://forum.gamer.com.tw/A.php?bsn=36730\n"
            "- 特玩網原神專區: http://www.te5.com/yuanshen/"
        )
        
        ai_config = types.GenerateContentConfig(
            max_output_tokens=1000,
            system_instruction=instruction_text
        )
        
        try:
            # 5. 送給 Gemini 生成最終的回應
            response = client.models.generate_content(
                model='gemini-3.1-flash-lite',
                contents=user_query,
                config=ai_config,
            )
            info = response.text if response.text else "抱歉，派蒙現在沒抓到數據，請稍後再試。"
        except Exception as e:
            info = f"發生錯誤: {str(e)}"
            
        return make_response(jsonify({"fulfillmentText": info}))


@app.route("/rate")
def rate():
    #本週新片
    url = "https://www.atmovies.com.tw/movie/new/"
    Data = requests.get(url)
    Data.encoding = "utf-8"
    sp = BeautifulSoup(Data.text, "html.parser")
    lastUpdate = sp.find(class_="smaller09").text[5:]
    print(lastUpdate)
    print()

    result=sp.select(".filmList")

    for x in result:
        title = x.find("a").text
        introduce = x.find("p").text

        movie_id = x.find("a").get("href").replace("/", "").replace("movie", "")
        hyperlink = "http://www.atmovies.com.tw/movie/" + movie_id
        picture = "https://www.atmovies.com.tw/photo101/" + movie_id + "/pm_" + movie_id + ".jpg"

        r = x.find(class_="runtime").find("img")
        rate = ""
        if r != None:
            rr = r.get("src").replace("/images/cer_", "").replace(".gif", "")
            if rr == "G":
                rate = "普遍級"
            elif rr == "P":
                rate = "保護級"
            elif rr == "F2":
                rate = "輔12級"
            elif rr == "F5":
                rate = "輔15級"
            else:
                rate = "限制級"

        t = x.find(class_="runtime").text

        t1 = t.find("片長")
        t2 = t.find("分")
        showLength = t[t1+3:t2]

        t1 = t.find("上映日期")
        t2 = t.find("上映廳數")
        showDate = t[t1+5:t2-8]

        doc = {
            "title": title,
            "introduce": introduce,
            "picture": picture,
            "hyperlink": hyperlink,
            "showDate": showDate,
            "showLength": int(showLength),
            "rate": rate,
            "lastUpdate": lastUpdate
        }

        db = firestore.client()
        doc_ref = db.collection("本週新片含分級").document(movie_id)
        doc_ref.set(doc)
    return "本週新片已爬蟲及存檔完畢，網站最近更新日期為：" + lastUpdate


@app.route("/weather", methods=["GET", "POST"])
def weather_query():
    result_text = ""
    if request.method == "POST":
        city = request.form.get("city", "")
        if city:
            city = city.replace("台", "臺")
            
            # 氣象署 API
            url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001?Authorization=rdec-key-123-45678-011121314&format=JSON&locationName={city}"
            
            try:
                response = requests.get(url, verify=False)
                data = json.loads(response.text)
                
                if data["records"]["location"]:
                    weather_element = data["records"]["location"][0]["weatherElement"]
                    weather = weather_element[0]["time"][0]["parameter"]["parameterName"]
                    rain = weather_element[1]["time"][0]["parameter"]["parameterName"]
                    
                    # 這是你要的 R 字串
                    result_text = f"{city} 目前天氣預報：<br>{weather}，降雨機率：{rain}%"
                else:
                    result_text = "找不到該縣市，請輸入正確名稱（如：臺中市）。"
            except Exception as e:
                result_text = f"連線錯誤：{e}"
                
    return render_template("weather.html", result=result_text)


@app.route("/road")
def road():
    R = ""
    url = "https://newdatacenter.taichung.gov.tw/api/v1/no-auth/resource.download?rid=a1b899c0-511f-4e3d-b22b-814982a97e41"
    Data = requests.get(url, verify=False)
    #print(Data.text)

    JsonData = json.loads(Data.text)
    for item in JsonData:
        R += item["路口名稱"] + ",總共發生" + item["總件數"] + "件事故<br>"
    return R

@app.route("/movie3", methods=["GET", "POST"])
def movie3():
    db = firestore.client()
    results = []
    keyword = ""
    
    if request.method == "POST":
        keyword = request.form.get("keyword")
        collection_ref = db.collection("電影2A")
        docs = collection_ref.get()

        for doc in docs:
            movie = doc.to_dict()
            if keyword in movie["title"]:
                results.append({
                    "title":  movie["title"],
                    "picture": movie["picture"],
                    "hyperlink": movie["hyperlink"],
                    "showDate": movie["showDate"],
                    "showLength": movie["showLength"],
                    "lastUpdate": movie["lastUpdate"]
                })

    return render_template("movie3.html", results=results, keyword=keyword)


@app.route("/movie2")
def movie2():
  url = "http://www.atmovies.com.tw/movie/next/"
  Data = requests.get(url)
  Data.encoding = "utf-8"
  sp = BeautifulSoup(Data.text, "html.parser")
  result=sp.select(".filmListAllX li")
  lastUpdate = sp.find("div", class_="smaller09").text[5:]

  for item in result:
    picture = item.find("img").get("src").replace(" ", "")
    title = item.find("div", class_="filmtitle").text
    movie_id = item.find("div", class_="filmtitle").find("a").get("href").replace("/", "").replace("movie", "")
    hyperlink = "http://www.atmovies.com.tw" + item.find("div", class_="filmtitle").find("a").get("href")
    show = item.find("div", class_="runtime").text.replace("上映日期：", "")
    show = show.replace("片長：", "")
    show = show.replace("分", "")
    showDate = show[0:10]
    showLength = show[13:]

    doc = {
        "title": title,
        "picture": picture,
        "hyperlink": hyperlink,
        "showDate": showDate,
        "showLength": showLength,
        "lastUpdate": lastUpdate
      }

    db = firestore.client()
    doc_ref = db.collection("電影2A").document(movie_id)
    doc_ref.set(doc)    
  return "近期上映電影已爬蟲及存檔完畢，網站最近更新日期為：" + lastUpdate 

@app.route("/movie1")
def movie1():
    R = ""
    url = "https://www.atmovies.com.tw/movie/next/"
    Data = requests.get(url)
    Data.encoding = "utf-8"
    #print(Data.text)
    sp = BeautifulSoup(Data.text, "html.parser")
    result=sp.select(".filmListAllX li")
    for item in result:
        introduce = "https://www.atmovies.com.tw" + item.find("a").get("href")
        R +=  "<a href=" + introduce + ">" + item.find("img").get("alt") + "</a><br>"
        post = "https://www.atmovies.com.tw" + item.find("img").get("src")
        R += "<img src=" + post + "> </img><br><br>" 
    return R    

@app.route("/spider1")
def spider1():
    R = ""
    url = "https://www1.pu.edu.tw/~tcyang/course.html"
    Data = requests.get(url)
    Data.encoding = "utf-8"
    sp = BeautifulSoup(Data.text, "html.parser")
    result=sp.select(".team-box a")

    for i in result:
        R += i.text + i.get("href") + "<br>" 
    return R

@app.route("/search", methods=["GET", "POST"])
def search():
    db = firestore.client()
    results = []
    keyword = ""
    
    if request.method == "POST":
        keyword = request.form.get("keyword")
        collection_ref = db.collection("tcyang")
        docs = collection_ref.get()

        for doc in docs:
            user = doc.to_dict()
            if keyword in user["name"]:
                results.append({
                    "name": user["name"],
                    "lab": user["lab"]
                })

    return render_template("search.html", results=results, keyword=keyword)


@app.route("/read2")
def read2():
    Result = ""
    keyword = "楊"
    db = firestore.client()
    collection_ref = db.collection("tcyang")    
    docs = collection_ref.get()
    for doc in docs: 
        teacher = doc.to_dict()
        if keyword in teacher["name"]:        
            Result += str(teacher) + "<br>"

    if Result == "":
        Result = "抱歉,查無此關鍵字姓名之老師資料"    
    return Result

@app.route("/read")
def read():
    Result = ""
    db = firestore.client()
    collection_ref = db.collection("tcyang")    
    docs = collection_ref.get()
    docs = collection_ref.order_by("lab", direction=firestore.Query.DESCENDING).get()
    for doc in docs:         
        Result += str(doc.to_dict()) + "<br>"    
    return Result

@app.route("/mis")
def course():
    return "<h1>資訊管理導論</h1><a href=/>返回首頁</a>"

@app.route("/today")
def today():
    now = datetime.now()
    return render_template("today.html", datetime=str(now))

@app.route("/about")
def about():
    return render_template("mis2a.html")

@app.route("/welcome", methods=["GET"])
def welcome():
    user = request.values.get("u")
    d = request.values.get("d")
    c = request.values.get("c")    
    return render_template("welcome.html", name= user, dep = d, course = c)


@app.route("/account", methods=["GET", "POST"])
def account():
    if request.method == "POST":
        user = request.form["user"]
        pwd = request.form["pwd"]
        result = "您輸入的帳號是：" + user + "; 密碼為：" + pwd 
        return result
    else:
        return render_template("account.html")


@app.route("/math", methods=["GET", "POST"])
def math():
    if request.method == "POST":
        x = int(request.form["x"])
        opt = request.form["opt"]
        y = int(request.form["y"])      
        result = "您輸入的是：" + str(x) + opt + str(y)
        
        if (opt == "/" and y == 0):
            result += "，除數不能為0"
        else:
            match opt:
                case "+":
                    r = x + y
                case "-":
                    r = x - y
                case "*":
                    r = x * y
                case "/":
                    r = x / y  # 修正：之前誤寫為 x - y
                case _:
                    return "未知運算符號"
            result += "=" + str(r)  + "<br><a href=/>返回首頁</a>"          
        return result
    else:
        return render_template("math.html")

@app.route('/cup', methods=["GET"])
def cup():
    # 檢查網址是否有 ?action=toss
    #action = request.args.get('action')
    action = request.values.get("action")
    result = None
    
    if action == 'toss':
        # 0 代表陽面，1 代表陰面
        x1 = random.randint(0, 1)
        x2 = random.randint(0, 1)
        
        # 判斷結果文字
        if x1 != x2:
            msg = "聖筊：表示神明允許、同意，或行事會順利。"
        elif x1 == 0:
            msg = "笑筊：表示神明一笑、不解，或者考慮中，行事狀況不明。"
        else:
            msg = "陰筊：表示神明否定、憤怒，或者不宜行事。"
            
        result = {
            "cup1": "/static/" + str(x1) + ".jpg",
            "cup2": "/static/" + str(x2) + ".jpg",
            "message": msg
        }
        
    return render_template('cup.html', result=result)



@app.route("/math2", methods=["GET", "POST"])
def math2():
    result = None
    if request.method == "POST":
        # 取得使用者輸入
        x = int(request.form.get("x"))
        opt = request.form.get("opt")
        y = int(request.form.get("y"))

        # 你的核心邏輯
        match opt:
            case "∧":
                result = x ** y
            case "√":
                if y != 0:
                    result = x ** (1/y)
                else:
                    result = "數學上不存在「0 次方根」"
            case _:
                result = "請輸入∧(次方)或√(根號)"
    return render_template("math2.html", result=result)


if __name__ == "__main__":
    app.run(debug=True)
