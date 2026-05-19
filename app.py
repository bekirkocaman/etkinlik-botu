from flask import Flask, render_template, request, jsonify, Response
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import urllib.parse
import urllib.request
import json
import os
import csv
import io
from datetime import datetime

app = Flask(__name__)

kapsam = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
TABLO_ID = "1lY3ncFUl5rzGvKi6F8P8l98ajbWYsdXHyKV1Qwm6kFU"
SERP_KEY = "4047ec625df667bbbd034bf5b53657d61ffa1b46a0551ed2d6d1932733abeed6"

SIMDI = datetime.now()
BU_YIL = SIMDI.year
BU_AY  = SIMDI.month

KATEGORILER = {
    "siber_guvenlik":    ["cybersecurity event", "hacking event", "CTF competition", "security conference"],
    "yazilim_teknoloji": ["software event", "tech meetup", "hackathon", "developer conference", "startup event"],
    "eglence_oyun":      ["gaming event", "esports tournament", "game jam", "gaming tournament"],
    "genel_etkinlik":    ["festival", "concert", "upcoming event"]
}

KATEGORI_ETIKET = {
    "siber_guvenlik":    "🔒 Siber Güvenlik",
    "yazilim_teknoloji": "💻 Yazılım/Teknoloji",
    "eglence_oyun":      "🎮 Eğlence/Oyun",
    "genel_etkinlik":    "📅 Genel Etkinlik"
}

GECMIS_ISARETLER = [
    "recap", "highlights", "was held", "took place", "concluded",
    "summary", "photos from", "thank you for attending", "wrap up"
]

AY_EN = ["january","february","march","april","may","june",
         "july","august","september","october","november","december"]
AY_TR = ["ocak","şubat","mart","nisan","mayıs","haziran",
         "temmuz","ağustos","eylül","ekim","kasım","aralık"]

PLATFORMLAR = ["facebook.com","instagram.com","linkedin.com","eventbrite.com","meetup.com"]

def gecmis_mi(baslik):
    metin = baslik.lower()
    if any(i in metin for i in GECMIS_ISARETLER):
        return True
    for yil in range(2018, BU_YIL):
        if str(yil) in metin:
            return True
    for ay_idx, ay in enumerate(AY_EN, start=1):
        if ay in metin and str(BU_YIL) in metin and ay_idx < BU_AY:
            return True
    for ay_idx, ay in enumerate(AY_TR, start=1):
        if ay in metin and str(BU_YIL) in metin and ay_idx < BU_AY:
            return True
    return False

def platform_bul(link):
    if "facebook.com"   in link: return "Facebook"
    if "instagram.com"  in link: return "Instagram"
    if "linkedin.com"   in link: return "LinkedIn"
    if "eventbrite.com" in link: return "Eventbrite"
    if "meetup.com"     in link: return "Meetup"
    return None

def serp_ara(sorgu, konum):
    """SerpAPI ile Google arama yapar, organik sonuçları döndürür"""
    platform_filtre = "site:facebook.com OR site:instagram.com OR site:linkedin.com OR site:eventbrite.com OR site:meetup.com"
    tam_sorgu = f"{sorgu} {konum} upcoming {BU_YIL} ({platform_filtre})"

    params = urllib.parse.urlencode({
        "q": tam_sorgu,
        "api_key": SERP_KEY,
        "num": 10,
        "hl": "en",
        "gl": "mk"
    })
    url = f"https://serpapi.com/search.json?{params}"

    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode())
        return data.get("organic_results", [])
    except Exception as e:
        print(f"SerpAPI hatası: {e}")
        return []

def tara(konum, kategoriler):
    arama_listesi = []
    for kat in kategoriler:
        if kat in KATEGORILER:
            for anahtar in KATEGORILER[kat]:
                arama_listesi.append((anahtar, kat))

    hafiza = set()
    toplam = 0

    for i, (sorgu, kat) in enumerate(arama_listesi):
        yuzde = int((i / len(arama_listesi)) * 100)
        yield f"data: {json.dumps({'tip':'ilerleme','mesaj':f'{sorgu} taranıyor... ({i+1}/{len(arama_listesi)})','yuzde':yuzde})}\n\n"

        sonuclar = serp_ara(sorgu, konum)

        for s in sonuclar:
            try:
                link   = s.get("link", "")
                baslik = s.get("title", "").strip()

                if not link or link in hafiza:
                    continue

                platform = platform_bul(link)
                if not platform:
                    continue

                if not baslik or len(baslik) < 3:
                    baslik = "Etkinlik"

                if gecmis_mi(baslik):
                    hafiza.add(link)
                    continue

                etkinlik = {
                    "baslik":       baslik,
                    "platform":     platform,
                    "kategori":     KATEGORI_ETIKET.get(kat, "📅 Genel Etkinlik"),
                    "kategori_key": kat,
                    "konum":        konum,
                    "link":         link
                }
                toplam += 1
                hafiza.add(link)
                yield f"data: {json.dumps({'tip':'etkinlik','veri':etkinlik})}\n\n"

            except Exception:
                continue

    yield f"data: {json.dumps({'tip':'bitti','toplam':toplam})}\n\n"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/tara")
def tara_endpoint():
    konum = request.args.get("konum", "Macedonia")
    kategoriler = request.args.getlist("kategoriler")
    if not kategoriler:
        kategoriler = list(KATEGORILER.keys())
    return Response(tara(konum, kategoriler), mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@app.route("/sheets", methods=["POST"])
def sheets_gonder():
    try:
        veriler = request.json.get("veriler", [])
        kimlik  = ServiceAccountCredentials.from_json_keyfile_name("kimlik.json", kapsam)
        client  = gspread.authorize(kimlik)
        tablo   = client.open_by_key(TABLO_ID).sheet1
        satirlar = [[v["baslik"],v["platform"],v["kategori"],v["konum"],v["link"]] for v in veriler]
        if not tablo.row_values(1):
            tablo.append_row(["Başlık","Platform","Kategori","Konum","Link"])
        tablo.insert_rows(satirlar, row=2)
        return jsonify({"basari":True,"mesaj":f"{len(satirlar)} etkinlik eklendi!"})
    except Exception as e:
        return jsonify({"basari":False,"mesaj":str(e)})

@app.route("/csv", methods=["POST"])
def csv_indir():
    veriler = request.json.get("veriler", [])
    output  = io.StringIO()
    writer  = csv.writer(output)
    writer.writerow(["Başlık","Platform","Kategori","Konum","Link"])
    for v in veriler:
        writer.writerow([v["baslik"],v["platform"],v["kategori"],v["konum"],v["link"]])
    output.seek(0)
    return Response(output.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition":"attachment; filename=etkinlikler.csv"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
