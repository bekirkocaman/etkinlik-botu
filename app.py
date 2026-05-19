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
import re

app = Flask(__name__)

kapsam = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
TABLO_ID = "1lY3ncFUl5rzGvKi6F8P8l98ajbWYsdXHyKV1Qwm6kFU"
SERP_KEY = "4047ec625df667bbbd034bf5b53657d61ffa1b46a0551ed2d6d1932733abeed6"

KATEGORILER = {
    "siber_guvenlik":    ["cybersecurity event", "hacking event", "CTF competition", "security conference"],
    "yazilim_teknoloji": ["software event", "tech meetup", "hackathon", "developer conference", "startup event"],
    "oyun":              ["gaming event", "esports tournament", "game jam", "gaming tournament", "LAN party"],
    "eglence":           ["party night", "bar event", "nightlife event", "Turkish night", "club event", "concert night", "festival party"],
    "genel_etkinlik":    ["festival", "concert", "upcoming event"]
}

KATEGORI_ETIKET = {
    "siber_guvenlik":    "🔒 Siber Güvenlik",
    "yazilim_teknoloji": "💻 Yazılım/Teknoloji",
    "oyun":              "🎮 Oyun",
    "eglence":           "🎉 Eğlence",
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

# Ay kısaltmaları (Jan, Feb, Mar...)
AY_KISALT = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"]

def tarih_gecmis_mi(metin):
    """
    Metinde geçen tarihleri bulur, geçmişte mi gelecekte mi kontrol eder.
    Geçmişteyse True döner.
    """
    su_an  = datetime.now()
    bu_yil = su_an.year
    bu_ay  = su_an.month
    bu_gun = su_an.day

    metin_lower = metin.lower()

    # "28 February 2026" veya "February 28, 2026" gibi tam tarih formatları
    # Önce yıl+ay kombinasyonunu bul
    for ay_idx, ay in enumerate(AY_EN, start=1):
        if ay in metin_lower:
            # Metinde bu ay ve bir yıl var mı?
            yil_eslesmeler = re.findall(r'\b(20\d{2})\b', metin)
            for yil_str in yil_eslesmeler:
                yil = int(yil_str)
                if yil < bu_yil:
                    return True  # Geçmiş yıl
                if yil == bu_yil and ay_idx < bu_ay:
                    return True  # Bu yılın geçmiş ayı
                if yil == bu_yil and ay_idx == bu_ay:
                    # Aynı ay — günü kontrol et
                    gun_eslesmeler = re.findall(r'\b(\d{1,2})\b', metin)
                    for gun_str in gun_eslesmeler:
                        gun = int(gun_str)
                        if 1 <= gun <= 31 and gun < bu_gun:
                            return True

    # Kısaltmalar: "Feb 28" veya "28 Feb"
    for ay_idx, ay in enumerate(AY_KISALT, start=1):
        if ay in metin_lower:
            yil_eslesmeler = re.findall(r'\b(20\d{2})\b', metin)
            for yil_str in yil_eslesmeler:
                yil = int(yil_str)
                if yil < bu_yil:
                    return True
                if yil == bu_yil and ay_idx < bu_ay:
                    return True

    # "MM/DD/YYYY" veya "DD.MM.YYYY" formatları
    tarih_pattern = re.findall(r'\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b', metin)
    for t in tarih_pattern:
        try:
            # DD.MM.YYYY olarak dene
            gun, ay, yil = int(t[0]), int(t[1]), int(t[2])
            if yil < bu_yil: return True
            if yil == bu_yil and ay < bu_ay: return True
            if yil == bu_yil and ay == bu_ay and gun < bu_gun: return True
        except Exception:
            pass

    return False

def gecmis_mi(baslik, snippet=""):
    su_an  = datetime.now()
    bu_yil = su_an.year
    bu_ay  = su_an.month

    # Başlık + snippet birleştir
    tam_metin = (baslik + " " + snippet).lower()

    # Geçmiş kelimeler
    if any(i in tam_metin for i in GECMIS_ISARETLER):
        return True

    # Tarih analizi — hem başlık hem snippet'te
    if tarih_gecmis_mi(baslik + " " + snippet):
        return True

    # Geçmiş yıllar
    for yil in range(2018, bu_yil):
        if str(yil) in tam_metin:
            return True

    # Bu yılın geçmiş ayları (İngilizce)
    for ay_idx, ay in enumerate(AY_EN, start=1):
        if ay in tam_metin and str(bu_yil) in tam_metin and ay_idx < bu_ay:
            return True

    # Bu yılın geçmiş ayları (Türkçe)
    for ay_idx, ay in enumerate(AY_TR, start=1):
        if ay in tam_metin and str(bu_yil) in tam_metin and ay_idx < bu_ay:
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
    su_an  = datetime.now()
    bu_yil = su_an.year
    platform_filtre = "site:facebook.com OR site:instagram.com OR site:linkedin.com OR site:eventbrite.com OR site:meetup.com"
    tam_sorgu = f"{sorgu} {konum} upcoming {bu_yil} ({platform_filtre})"
    params = urllib.parse.urlencode({
        "q": tam_sorgu, "api_key": SERP_KEY,
        "num": 10, "hl": "en", "gl": "mk"
    })
    try:
        with urllib.request.urlopen(f"https://serpapi.com/search.json?{params}", timeout=15) as r:
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

        for s in serp_ara(sorgu, konum):
            try:
                link    = s.get("link", "")
                baslik  = s.get("title", "").strip()
                snippet = s.get("snippet", "").strip()  # ← açıklama metni de alınıyor

                if not link or link in hafiza: continue
                platform = platform_bul(link)
                if not platform: continue
                if not baslik or len(baslik) < 3: baslik = "Etkinlik"

                # Snippet de kontrol ediliyor
                if gecmis_mi(baslik, snippet):
                    hafiza.add(link)
                    continue

                etkinlik = {
                    "baslik": baslik, "platform": platform,
                    "kategori": KATEGORI_ETIKET.get(kat, "📅 Genel Etkinlik"),
                    "kategori_key": kat, "konum": konum, "link": link
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
