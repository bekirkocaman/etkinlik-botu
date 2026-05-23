"""
Etkinlik Avcisi — SerpAPI ile sosyal platformlarda etkinlik arayan Flask uygulamasi.
"""

import csv
import io
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime

import gspread
from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request
from oauth2client.service_account import ServiceAccountCredentials

load_dotenv()

app = Flask(__name__)

SERP_API_KEY = os.getenv("SERP_API_KEY", "")
TABLO_ID = os.getenv("GOOGLE_SHEETS_ID", "")
KIMLIK_DOSYASI = os.getenv("GOOGLE_CREDENTIALS_FILE", "kimlik.json")

KAPSAM = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

KATEGORILER = {
    "siber_guvenlik": ["cybersecurity event", "hacking event", "CTF competition", "security conference"],
    "yazilim_teknoloji": ["software event", "tech meetup", "hackathon", "developer conference", "startup event"],
    "oyun": ["gaming event", "esports tournament", "game jam", "gaming tournament", "LAN party"],
    "eglence": ["party night", "bar event", "nightlife event", "Turkish night", "club event", "concert night", "festival party"],
    "genel_etkinlik": ["festival", "concert", "upcoming event"],
}

KATEGORI_ETIKET = {
    "siber_guvenlik": "🔒 Siber Güvenlik",
    "yazilim_teknoloji": "💻 Yazılım/Teknoloji",
    "oyun": "🎮 Oyun",
    "eglence": "🎉 Eğlence",
    "genel_etkinlik": "📅 Genel Etkinlik",
}

GECMIS_ISARETLER = [
    "recap", "highlights", "was held", "took place", "concluded",
    "summary", "photos from", "thank you for attending", "wrap up",
]

AY_EN = ["january", "february", "march", "april", "may", "june",
         "july", "august", "september", "october", "november", "december"]
AY_TR = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran",
         "temmuz", "ağustos", "eylül", "ekim", "kasım", "aralık"]
AY_KISALT = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


def tarih_gecmis_mi(metin: str) -> bool:
    su_an = datetime.now()
    bu_yil, bu_ay, bu_gun = su_an.year, su_an.month, su_an.day
    metin_lower = metin.lower()

    for ay_idx, ay in enumerate(AY_EN, start=1):
        if ay in metin_lower:
            for yil_str in re.findall(r"\b(20\d{2})\b", metin):
                yil = int(yil_str)
                if yil < bu_yil:
                    return True
                if yil == bu_yil and ay_idx < bu_ay:
                    return True
                if yil == bu_yil and ay_idx == bu_ay:
                    for gun_str in re.findall(r"\b(\d{1,2})\b", metin):
                        gun = int(gun_str)
                        if 1 <= gun <= 31 and gun < bu_gun:
                            return True

    for ay_idx, ay in enumerate(AY_KISALT, start=1):
        if ay in metin_lower:
            for yil_str in re.findall(r"\b(20\d{2})\b", metin):
                yil = int(yil_str)
                if yil < bu_yil:
                    return True
                if yil == bu_yil and ay_idx < bu_ay:
                    return True

    for t in re.findall(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", metin):
        try:
            gun, ay, yil = int(t[0]), int(t[1]), int(t[2])
            if yil < bu_yil:
                return True
            if yil == bu_yil and ay < bu_ay:
                return True
            if yil == bu_yil and ay == bu_ay and gun < bu_gun:
                return True
        except ValueError:
            pass

    return False


def gecmis_mi(baslik: str, snippet: str = "") -> bool:
    su_an = datetime.now()
    bu_yil, bu_ay = su_an.year, su_an.month
    tam_metin = (baslik + " " + snippet).lower()

    if any(i in tam_metin for i in GECMIS_ISARETLER):
        return True
    if tarih_gecmis_mi(baslik + " " + snippet):
        return True

    for yil in range(2018, bu_yil):
        if str(yil) in tam_metin:
            return True

    for ay_idx, ay in enumerate(AY_EN, start=1):
        if ay in tam_metin and str(bu_yil) in tam_metin and ay_idx < bu_ay:
            return True

    for ay_idx, ay in enumerate(AY_TR, start=1):
        if ay in tam_metin and str(bu_yil) in tam_metin and ay_idx < bu_ay:
            return True

    return False


def platform_bul(link: str):
    if "facebook.com" in link:
        return "Facebook"
    if "instagram.com" in link:
        return "Instagram"
    if "linkedin.com" in link:
        return "LinkedIn"
    if "eventbrite.com" in link:
        return "Eventbrite"
    if "meetup.com" in link:
        return "Meetup"
    return None


def serp_ara(sorgu: str, konum: str):
    if not SERP_API_KEY:
        print("SERP_API_KEY eksik — .env dosyasini kontrol edin.")
        return []

    bu_yil = datetime.now().year
    platform_filtre = (
        "site:facebook.com OR site:instagram.com OR site:linkedin.com "
        "OR site:eventbrite.com OR site:meetup.com"
    )
    tam_sorgu = f"{sorgu} {konum} upcoming {bu_yil} ({platform_filtre})"
    params = urllib.parse.urlencode({
        "q": tam_sorgu,
        "api_key": SERP_API_KEY,
        "num": 10,
        "hl": "en",
        "gl": "mk",
    })
    try:
        with urllib.request.urlopen(
            f"https://serpapi.com/search.json?{params}", timeout=15
        ) as r:
            data = json.loads(r.read().decode())
        return data.get("organic_results", [])
    except Exception as e:
        print(f"SerpAPI hatasi: {e}")
        return []


def tara(konum: str, kategoriler: list):
    arama_listesi = []
    for kat in kategoriler:
        if kat in KATEGORILER:
            for anahtar in KATEGORILER[kat]:
                arama_listesi.append((anahtar, kat))

    hafiza = set()
    toplam = 0

    for i, (sorgu, kat) in enumerate(arama_listesi):
        yuzde = int((i / len(arama_listesi)) * 100)
        yield f"data: {json.dumps({'tip': 'ilerleme', 'mesaj': f'{sorgu} taranıyor... ({i+1}/{len(arama_listesi)})', 'yuzde': yuzde})}\n\n"

        for s in serp_ara(sorgu, konum):
            try:
                link = s.get("link", "")
                baslik = s.get("title", "").strip()
                snippet = s.get("snippet", "").strip()

                if not link or link in hafiza:
                    continue
                platform = platform_bul(link)
                if not platform:
                    continue
                if not baslik or len(baslik) < 3:
                    baslik = "Etkinlik"

                if gecmis_mi(baslik, snippet):
                    hafiza.add(link)
                    continue

                etkinlik = {
                    "baslik": baslik,
                    "platform": platform,
                    "kategori": KATEGORI_ETIKET.get(kat, "📅 Genel Etkinlik"),
                    "kategori_key": kat,
                    "konum": konum,
                    "link": link,
                }
                toplam += 1
                hafiza.add(link)
                yield f"data: {json.dumps({'tip': 'etkinlik', 'veri': etkinlik})}\n\n"
            except Exception:
                continue

    yield f"data: {json.dumps({'tip': 'bitti', 'toplam': toplam})}\n\n"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/tara")
def tara_endpoint():
    konum = request.args.get("konum", "Macedonia")
    kategoriler = request.args.getlist("kategoriler")
    if not kategoriler:
        kategoriler = list(KATEGORILER.keys())
    return Response(
        tara(konum, kategoriler),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/sheets", methods=["POST"])
def sheets_gonder():
    if not TABLO_ID or not os.path.exists(KIMLIK_DOSYASI):
        return jsonify({
            "basari": False,
            "mesaj": "Google Sheets yapilandirmasi eksik (.env ve kimlik.json)",
        })

    try:
        veriler = request.json.get("veriler", [])
        kimlik = ServiceAccountCredentials.from_json_keyfile_name(KIMLIK_DOSYASI, KAPSAM)
        client = gspread.authorize(kimlik)
        tablo = client.open_by_key(TABLO_ID).sheet1
        satirlar = [
            [v["baslik"], v["platform"], v["kategori"], v["konum"], v["link"]]
            for v in veriler
        ]
        if not tablo.row_values(1):
            tablo.append_row(["Başlık", "Platform", "Kategori", "Konum", "Link"])
        tablo.insert_rows(satirlar, row=2)
        return jsonify({"basari": True, "mesaj": f"{len(satirlar)} etkinlik eklendi!"})
    except Exception as e:
        return jsonify({"basari": False, "mesaj": str(e)})


@app.route("/csv", methods=["POST"])
def csv_indir():
    veriler = request.json.get("veriler", [])
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Başlık", "Platform", "Kategori", "Konum", "Link"])
    for v in veriler:
        writer.writerow([v["baslik"], v["platform"], v["kategori"], v["konum"], v["link"]])
    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=etkinlikler.csv"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(host="0.0.0.0", port=port, debug=debug)
