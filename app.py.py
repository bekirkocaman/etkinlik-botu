from flask import Flask, render_template, request, jsonify, Response
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from playwright.sync_api import sync_playwright
import urllib.parse
import time
import json
import os
import csv
import io
from datetime import datetime

app = Flask(__name__)

kapsam = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
TABLO_ID = "1lY3ncFUl5rzGvKi6F8P8l98ajbWYsdXHyKV1Qwm6kFU"

SIMDI = datetime.now()
BU_YIL = SIMDI.year
BU_AY = SIMDI.month  # 5 = Mayıs

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
    "summary", "photos from", "thank you for attending", "wrap up", "wrap-up",
    "geçti", "tamamlandı", "bitti", "düzenlendi"
]

AY_EN = ["january","february","march","april","may","june",
         "july","august","september","october","november","december"]
AY_TR = ["ocak","şubat","mart","nisan","mayıs","haziran",
         "temmuz","ağustos","eylül","ekim","kasım","aralık"]

def url_desifre_et(ham_url):
    if not ham_url:
        return ""
    if "/url?q=" in ham_url:
        p = urllib.parse.parse_qs(urllib.parse.urlparse(ham_url).query)
        if 'q' in p:
            return p['q'][0]
    return ham_url

def gecmis_mi(baslik):
    metin = baslik.lower()
    if any(i in metin for i in GECMIS_ISARETLER):
        return True
    # 2024 ve öncesi yıllar
    for yil in range(2018, BU_YIL):
        if str(yil) in metin:
            return True
    # Bu yılın geçmiş ayları (Mayıs dahil değil — Mayıs gösterilsin)
    for ay_idx, ay in enumerate(AY_EN, start=1):
        if ay in metin and str(BU_YIL) in metin and ay_idx < BU_AY:
            return True
    for ay_idx, ay in enumerate(AY_TR, start=1):
        if ay in metin and str(BU_YIL) in metin and ay_idx < BU_AY:
            return True
    return False

def guvvenli_selector_al(sayfa):
    for deneme in range(3):
        try:
            sayfa.wait_for_load_state("domcontentloaded", timeout=10000)
            sayfa.wait_for_load_state("networkidle", timeout=15000)
            return sayfa.query_selector_all("a")
        except Exception:
            if deneme < 2:
                time.sleep(2)
            else:
                return []

def tara(konum, kategoriler):
    arama_listesi = []
    for kat in kategoriler:
        if kat in KATEGORILER:
            for anahtar in KATEGORILER[kat]:
                arama_listesi.append((anahtar, kat))

    hafiza = set()
    toplam = 0

    with sync_playwright() as p:
        tarayici = p.chromium.launch(headless=True, args=[
            "--no-sandbox","--disable-setuid-sandbox",
            "--disable-dev-shm-usage","--disable-gpu"
        ])
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        sayfa = tarayici.new_page(user_agent=ua)

        platform_filtre = "(site:facebook.com OR site:instagram.com OR site:linkedin.com OR site:eventbrite.com OR site:meetup.com)"
        gelecek = f"upcoming {BU_YIL} OR {BU_YIL+1}"

        for i, (sorgu, kat) in enumerate(arama_listesi):
            yuzde = int((i / len(arama_listesi)) * 100)
            yield f"data: {json.dumps({'tip':'ilerleme','mesaj':f'{sorgu} taranıyor... ({i+1}/{len(arama_listesi)})','yuzde':yuzde})}\n\n"

            url = f"https://www.google.com/search?q={urllib.parse.quote(f'{sorgu} {konum} {gelecek} {platform_filtre}')}"
            try:
                sayfa.goto(url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                sayfa.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            elementler = guvvenli_selector_al(sayfa)

            for el in elementler:
                try:
                    href = url_desifre_et(el.get_attribute("href") or "")
                    if not href or href in hafiza or "google.com" in href:
                        continue

                    is_fb  = "facebook.com"   in href
                    is_ig  = "instagram.com"  in href
                    is_lin = "linkedin.com"   in href
                    is_eb  = "eventbrite.com" in href
                    is_mu  = "meetup.com"     in href

                    if not any([is_fb, is_ig, is_lin, is_eb, is_mu]):
                        continue

                    metin  = el.inner_text().strip().replace("\n", " ")
                    baslik = metin if (metin and len(metin) > 3) else "Etkinlik"

                    cop = ["çevir","benzer","önbellek","tarafından","cached","similar"]
                    if any(c in baslik.lower() for c in cop):
                        continue

                    if gecmis_mi(baslik):
                        hafiza.add(href)
                        continue

                    platform = ("Facebook" if is_fb else "Instagram" if is_ig else
                                "LinkedIn" if is_lin else "Eventbrite" if is_eb else "Meetup")

                    etkinlik = {
                        "baslik": baslik,
                        "platform": platform,
                        "kategori": KATEGORI_ETIKET.get(kat, "📅 Genel Etkinlik"),
                        "kategori_key": kat,
                        "konum": konum,
                        "link": href
                    }
                    toplam += 1
                    hafiza.add(href)
                    yield f"data: {json.dumps({'tip':'etkinlik','veri':etkinlik})}\n\n"
                except Exception:
                    continue

            if i < len(arama_listesi) - 1:
                time.sleep(3)

        tarayici.close()

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
