"""Settings page and controller-accessible selectors for the Tk desktop app."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import messagebox

from display_preferences import COMMON_ZONES, DEFAULTS

TEXT = {
    "en": {
        "settings": "Settings",
        "timezone": "Time Zone",
        "units": "Weather Unit",
        "celsius": "℃ Celsius",
        "fahrenheit": "℉ Fahrenheit",
        "country": "Country / Region",
        "all": "All Countries / Regions",
        "more": "More Cities",
        "offline": "Local cities shown; online search unavailable.",
        "format": "Time Format",
        "dst": "Automatic DST",
        "weather": "Weather Location",
        "auto": "Automatic (IP)",
        "manual": "Choose a City",
        "system": "Follow System",
        "search": "Search",
        "back": "‹ Back",
        "on": "On",
        "off": "Off",
        "update": "Online Update",
        "unavailable": "Not Enabled",
        "version": "Software Version",
        "12": "12-hour",
        "24": "24-hour",
        "none": "No results. Try a city or country.",
        "hint": "Common cities work offline; Search expands online",
        "saving": "Saving…",
    },
    "zh": {
        "settings": "设置",
        "timezone": "时区",
        "units": "天气单位",
        "celsius": "℃ 摄氏度",
        "fahrenheit": "℉ 华氏度",
        "country": "国家／地区",
        "all": "全部国家／地区",
        "more": "更多城市",
        "offline": "已显示本机城市，联网扩展暂不可用。",
        "format": "时间格式",
        "dst": "自动夏令时",
        "weather": "天气地址",
        "auto": "自动定位（IP）",
        "manual": "手动选择城市",
        "system": "跟随系统",
        "search": "搜索",
        "back": "‹ 返回",
        "on": "开",
        "off": "关",
        "update": "在线升级",
        "unavailable": "未启用",
        "version": "软件版本",
        "12": "12小时制",
        "24": "24小时制",
        "none": "没有匹配结果，请尝试城市或国家名称。",
        "hint": "常用城市可离线选择；搜索可联网扩展",
        "saving": "保存中…",
    },
}

# Settings copy follows the same SteamOS language identifiers as the main
# application.  Keep the values compact because these labels are rendered in
# fixed-width controller rows on both Deck surfaces.
TEXT.update(
    {
        "ar": {
            "settings": "الإعدادات",
            "timezone": "المنطقة الزمنية",
            "units": "وحدة الطقس",
            "celsius": "℃ مئوية",
            "fahrenheit": "℉ فهرنهايت",
            "format": "تنسيق الوقت",
            "dst": "التوقيت الصيفي التلقائي",
            "weather": "موقع الطقس",
            "country": "الدولة / المنطقة",
            "all": "كل الدول / المناطق",
            "more": "مدن أخرى",
            "auto": "تلقائي (IP)",
            "manual": "اختيار مدينة",
            "system": "اتباع النظام",
            "search": "بحث",
            "back": "‹ رجوع",
            "on": "تشغيل",
            "off": "إيقاف",
            "update": "تحديث عبر الإنترنت",
            "unavailable": "غير مفعّل",
            "version": "إصدار البرنامج",
            "12": "12 ساعة",
            "24": "24 ساعة",
            "none": "لا توجد نتائج.",
            "hint": "ابحث عن مدينة / منطقة",
            "saving": "جارٍ الحفظ…",
            "offline": "عُرضت المدن المحلية؛ البحث عبر الإنترنت غير متاح.",
        },
        "pt-br": {
            "settings": "Configurações",
            "timezone": "Fuso horário",
            "units": "Unidade do clima",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Formato da hora",
            "dst": "Horário de verão automático",
            "weather": "Local do clima",
            "country": "País / região",
            "all": "Todos os países / regiões",
            "more": "Mais cidades",
            "auto": "Automático (IP)",
            "manual": "Escolher cidade",
            "system": "Seguir sistema",
            "search": "Pesquisar",
            "back": "‹ Voltar",
            "on": "Ligado",
            "off": "Desligado",
            "update": "Atualização online",
            "unavailable": "Desativado",
            "version": "Versão do software",
            "12": "12 horas",
            "24": "24 horas",
            "none": "Nenhum resultado.",
            "hint": "Pesquisar cidade / região",
            "saving": "Salvando…",
            "offline": "Cidades locais exibidas; busca online indisponível.",
        },
        "bg": {
            "settings": "Настройки",
            "timezone": "Часова зона",
            "units": "Метео единица",
            "celsius": "℃ Целзий",
            "fahrenheit": "℉ Фаренхайт",
            "format": "Формат на часа",
            "dst": "Автоматично лятно време",
            "weather": "Местоположение за времето",
            "country": "Държава / регион",
            "all": "Всички държави / региони",
            "more": "Още градове",
            "auto": "Автоматично (IP)",
            "manual": "Избор на град",
            "system": "По системата",
            "search": "Търсене",
            "back": "‹ Назад",
            "on": "Вкл.",
            "off": "Изкл.",
            "update": "Онлайн актуализация",
            "unavailable": "Не е включено",
            "version": "Версия на софтуера",
            "12": "12 часа",
            "24": "24 часа",
            "none": "Няма резултати.",
            "hint": "Търсене на град / регион",
            "saving": "Записване…",
            "offline": "Показани са местни градове; онлайн търсенето не е налично.",
        },
        "cs": {
            "settings": "Nastavení",
            "timezone": "Časové pásmo",
            "units": "Jednotka počasí",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Formát času",
            "dst": "Automatický letní čas",
            "weather": "Místo počasí",
            "country": "Země / oblast",
            "all": "Všechny země / oblasti",
            "more": "Další města",
            "auto": "Automaticky (IP)",
            "manual": "Vybrat město",
            "system": "Podle systému",
            "search": "Hledat",
            "back": "‹ Zpět",
            "on": "Zapnuto",
            "off": "Vypnuto",
            "update": "Online aktualizace",
            "unavailable": "Není aktivní",
            "version": "Verze softwaru",
            "12": "12 hodin",
            "24": "24 hodin",
            "none": "Nenalezeny žádné výsledky.",
            "hint": "Hledat město / oblast",
            "saving": "Ukládání…",
            "offline": "Zobrazena místní města; online hledání není dostupné.",
        },
        "da": {
            "settings": "Indstillinger",
            "timezone": "Tidszone",
            "units": "Vejrenhed",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Tidsformat",
            "dst": "Automatisk sommertid",
            "weather": "Vejrlokation",
            "country": "Land / område",
            "all": "Alle lande / områder",
            "more": "Flere byer",
            "auto": "Automatisk (IP)",
            "manual": "Vælg en by",
            "system": "Følg systemet",
            "search": "Søg",
            "back": "‹ Tilbage",
            "on": "Til",
            "off": "Fra",
            "update": "Onlineopdatering",
            "unavailable": "Ikke aktiveret",
            "version": "Softwareversion",
            "12": "12 timer",
            "24": "24 timer",
            "none": "Ingen resultater.",
            "hint": "Søg by / område",
            "saving": "Gemmer…",
            "offline": "Lokale byer vises; onlinesøgning er ikke tilgængelig.",
        },
        "nl": {
            "settings": "Instellingen",
            "timezone": "Tijdzone",
            "units": "Weereenheid",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Tijdnotatie",
            "dst": "Automatische zomertijd",
            "weather": "Weerlocatie",
            "country": "Land / regio",
            "all": "Alle landen / regio’s",
            "more": "Meer steden",
            "auto": "Automatisch (IP)",
            "manual": "Stad kiezen",
            "system": "Systeem volgen",
            "search": "Zoeken",
            "back": "‹ Terug",
            "on": "Aan",
            "off": "Uit",
            "update": "Online bijwerken",
            "unavailable": "Niet ingeschakeld",
            "version": "Softwareversie",
            "12": "12 uur",
            "24": "24 uur",
            "none": "Geen resultaten.",
            "hint": "Zoek stad / regio",
            "saving": "Opslaan…",
            "offline": "Lokale steden weergegeven; online zoeken is niet beschikbaar.",
        },
        "fi": {
            "settings": "Asetukset",
            "timezone": "Aikavyöhyke",
            "units": "Sääyksikkö",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Aikamuoto",
            "dst": "Automaattinen kesäaika",
            "weather": "Sääsijainti",
            "country": "Maa / alue",
            "all": "Kaikki maat / alueet",
            "more": "Lisää kaupunkeja",
            "auto": "Automaattinen (IP)",
            "manual": "Valitse kaupunki",
            "system": "Järjestelmän mukaan",
            "search": "Hae",
            "back": "‹ Takaisin",
            "on": "Päällä",
            "off": "Pois",
            "update": "Verkkopäivitys",
            "unavailable": "Ei käytössä",
            "version": "Ohjelmistoversio",
            "12": "12 tuntia",
            "24": "24 tuntia",
            "none": "Ei tuloksia.",
            "hint": "Hae kaupunkia / aluetta",
            "saving": "Tallennetaan…",
            "offline": "Paikalliset kaupungit näytetään; verkkohaku ei ole käytettävissä.",
        },
        "fr": {
            "settings": "Paramètres",
            "timezone": "Fuseau horaire",
            "units": "Unité météo",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Format de l’heure",
            "dst": "Heure d’été automatique",
            "weather": "Lieu météo",
            "country": "Pays / région",
            "all": "Tous les pays / régions",
            "more": "Plus de villes",
            "auto": "Automatique (IP)",
            "manual": "Choisir une ville",
            "system": "Suivre le système",
            "search": "Rechercher",
            "back": "‹ Retour",
            "on": "Activé",
            "off": "Désactivé",
            "update": "Mise à jour en ligne",
            "unavailable": "Non activé",
            "version": "Version du logiciel",
            "12": "12 heures",
            "24": "24 heures",
            "none": "Aucun résultat.",
            "hint": "Rechercher une ville / région",
            "saving": "Enregistrement…",
            "offline": "Villes locales affichées ; recherche en ligne indisponible.",
        },
        "de": {
            "settings": "Einstellungen",
            "timezone": "Zeitzone",
            "units": "Wetter-Einheit",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Zeitformat",
            "dst": "Automatische Sommerzeit",
            "weather": "Wetterstandort",
            "country": "Land / Region",
            "all": "Alle Länder / Regionen",
            "more": "Weitere Städte",
            "auto": "Automatisch (IP)",
            "manual": "Stadt auswählen",
            "system": "System folgen",
            "search": "Suchen",
            "back": "‹ Zurück",
            "on": "Ein",
            "off": "Aus",
            "update": "Online-Update",
            "unavailable": "Nicht aktiviert",
            "version": "Softwareversion",
            "12": "12 Stunden",
            "24": "24 Stunden",
            "none": "Keine Ergebnisse.",
            "hint": "Stadt / Region suchen",
            "saving": "Speichern…",
            "offline": "Lokale Städte angezeigt; Onlinesuche nicht verfügbar.",
        },
        "el": {
            "settings": "Ρυθμίσεις",
            "timezone": "Ζώνη ώρας",
            "units": "Μονάδα καιρού",
            "celsius": "℃ Κελσίου",
            "fahrenheit": "℉ Φαρενάιτ",
            "format": "Μορφή ώρας",
            "dst": "Αυτόματη θερινή ώρα",
            "weather": "Τοποθεσία καιρού",
            "country": "Χώρα / περιοχή",
            "all": "Όλες οι χώρες / περιοχές",
            "more": "Περισσότερες πόλεις",
            "auto": "Αυτόματα (IP)",
            "manual": "Επιλογή πόλης",
            "system": "Ακολούθηση συστήματος",
            "search": "Αναζήτηση",
            "back": "‹ Πίσω",
            "on": "Ενεργό",
            "off": "Ανενεργό",
            "update": "Online ενημέρωση",
            "unavailable": "Δεν είναι ενεργό",
            "version": "Έκδοση λογισμικού",
            "12": "12 ώρες",
            "24": "24 ώρες",
            "none": "Δεν βρέθηκαν αποτελέσματα.",
            "hint": "Αναζήτηση πόλης / περιοχής",
            "saving": "Αποθήκευση…",
            "offline": "Εμφανίζονται τοπικές πόλεις· η online αναζήτηση δεν είναι διαθέσιμη.",
        },
        "hu": {
            "settings": "Beállítások",
            "timezone": "Időzóna",
            "units": "Időjárási egység",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Időformátum",
            "dst": "Automatikus nyári idő",
            "weather": "Időjárási hely",
            "country": "Ország / régió",
            "all": "Minden ország / régió",
            "more": "További városok",
            "auto": "Automatikus (IP)",
            "manual": "Város választása",
            "system": "Rendszer követése",
            "search": "Keresés",
            "back": "‹ Vissza",
            "on": "Be",
            "off": "Ki",
            "update": "Online frissítés",
            "unavailable": "Nincs engedélyezve",
            "version": "Szoftververzió",
            "12": "12 óra",
            "24": "24 óra",
            "none": "Nincs találat.",
            "hint": "Város / régió keresése",
            "saving": "Mentés…",
            "offline": "Helyi városok láthatók; az online keresés nem érhető el.",
        },
        "id": {
            "settings": "Pengaturan",
            "timezone": "Zona waktu",
            "units": "Satuan cuaca",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Format waktu",
            "dst": "Waktu musim panas otomatis",
            "weather": "Lokasi cuaca",
            "country": "Negara / wilayah",
            "all": "Semua negara / wilayah",
            "more": "Kota lainnya",
            "auto": "Otomatis (IP)",
            "manual": "Pilih kota",
            "system": "Ikuti sistem",
            "search": "Cari",
            "back": "‹ Kembali",
            "on": "Aktif",
            "off": "Nonaktif",
            "update": "Pembaruan online",
            "unavailable": "Tidak aktif",
            "version": "Versi perangkat lunak",
            "12": "12 jam",
            "24": "24 jam",
            "none": "Tidak ada hasil.",
            "hint": "Cari kota / wilayah",
            "saving": "Menyimpan…",
            "offline": "Kota lokal ditampilkan; pencarian online tidak tersedia.",
        },
        "it": {
            "settings": "Impostazioni",
            "timezone": "Fuso orario",
            "units": "Unità meteo",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Formato ora",
            "dst": "Ora legale automatica",
            "weather": "Posizione meteo",
            "country": "Paese / regione",
            "all": "Tutti i paesi / regioni",
            "more": "Altre città",
            "auto": "Automatico (IP)",
            "manual": "Scegli città",
            "system": "Segui sistema",
            "search": "Cerca",
            "back": "‹ Indietro",
            "on": "Attivo",
            "off": "Disattivo",
            "update": "Aggiornamento online",
            "unavailable": "Non attivo",
            "version": "Versione software",
            "12": "12 ore",
            "24": "24 ore",
            "none": "Nessun risultato.",
            "hint": "Cerca città / regione",
            "saving": "Salvataggio…",
            "offline": "Città locali mostrate; ricerca online non disponibile.",
        },
        "ja": {
            "settings": "設定",
            "timezone": "タイムゾーン",
            "units": "天気単位",
            "celsius": "℃ 摂氏",
            "fahrenheit": "℉ 華氏",
            "format": "時刻形式",
            "dst": "自動夏時間",
            "weather": "天気の場所",
            "country": "国 / 地域",
            "all": "すべての国 / 地域",
            "more": "他の都市",
            "auto": "自動 (IP)",
            "manual": "都市を選択",
            "system": "システムに従う",
            "search": "検索",
            "back": "‹ 戻る",
            "on": "オン",
            "off": "オフ",
            "update": "オンライン更新",
            "unavailable": "無効",
            "version": "ソフトウェアバージョン",
            "12": "12時間",
            "24": "24時間",
            "none": "結果がありません。",
            "hint": "都市 / 地域を検索",
            "saving": "保存中…",
            "offline": "ローカル都市を表示中。オンライン検索は利用できません。",
        },
        "ko": {
            "settings": "설정",
            "timezone": "시간대",
            "units": "날씨 단위",
            "celsius": "℃ 섭씨",
            "fahrenheit": "℉ 화씨",
            "format": "시간 형식",
            "dst": "자동 일광 절약 시간",
            "weather": "날씨 위치",
            "country": "국가 / 지역",
            "all": "모든 국가 / 지역",
            "more": "더 많은 도시",
            "auto": "자동 (IP)",
            "manual": "도시 선택",
            "system": "시스템 따르기",
            "search": "검색",
            "back": "‹ 뒤로",
            "on": "켜짐",
            "off": "꺼짐",
            "update": "온라인 업데이트",
            "unavailable": "사용 안 함",
            "version": "소프트웨어 버전",
            "12": "12시간",
            "24": "24시간",
            "none": "결과 없음.",
            "hint": "도시 / 지역 검색",
            "saving": "저장 중…",
            "offline": "로컬 도시를 표시합니다. 온라인 검색을 사용할 수 없습니다.",
        },
        "es-419": {
            "settings": "Configuración",
            "timezone": "Zona horaria",
            "units": "Unidad meteorológica",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Formato de hora",
            "dst": "Horario de verano automático",
            "weather": "Ubicación del clima",
            "country": "País / región",
            "all": "Todos los países / regiones",
            "more": "Más ciudades",
            "auto": "Automático (IP)",
            "manual": "Elegir ciudad",
            "system": "Seguir sistema",
            "search": "Buscar",
            "back": "‹ Atrás",
            "on": "Activado",
            "off": "Desactivado",
            "update": "Actualización en línea",
            "unavailable": "No activado",
            "version": "Versión del software",
            "12": "12 horas",
            "24": "24 horas",
            "none": "Sin resultados.",
            "hint": "Buscar ciudad / región",
            "saving": "Guardando…",
            "offline": "Se muestran ciudades locales; la búsqueda en línea no está disponible.",
        },
        "ms": {
            "settings": "Tetapan",
            "timezone": "Zon waktu",
            "units": "Unit cuaca",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Format masa",
            "dst": "Waktu musim panas automatik",
            "weather": "Lokasi cuaca",
            "country": "Negara / wilayah",
            "all": "Semua negara / wilayah",
            "more": "Lagi bandar",
            "auto": "Automatik (IP)",
            "manual": "Pilih bandar",
            "system": "Ikut sistem",
            "search": "Cari",
            "back": "‹ Kembali",
            "on": "Hidup",
            "off": "Mati",
            "update": "Kemas kini dalam talian",
            "unavailable": "Tidak didayakan",
            "version": "Versi perisian",
            "12": "12 jam",
            "24": "24 jam",
            "none": "Tiada hasil.",
            "hint": "Cari bandar / wilayah",
            "saving": "Menyimpan…",
            "offline": "Bandar tempatan dipaparkan; carian dalam talian tidak tersedia.",
        },
        "no": {
            "settings": "Innstillinger",
            "timezone": "Tidssone",
            "units": "Værenhet",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Tidsformat",
            "dst": "Automatisk sommertid",
            "weather": "Værsted",
            "country": "Land / region",
            "all": "Alle land / regioner",
            "more": "Flere byer",
            "auto": "Automatisk (IP)",
            "manual": "Velg by",
            "system": "Følg systemet",
            "search": "Søk",
            "back": "‹ Tilbake",
            "on": "På",
            "off": "Av",
            "update": "Nettoppdatering",
            "unavailable": "Ikke aktivert",
            "version": "Programvareversjon",
            "12": "12 timer",
            "24": "24 timer",
            "none": "Ingen resultater.",
            "hint": "Søk etter by / region",
            "saving": "Lagrer…",
            "offline": "Lokale byer vises; nettsøk er ikke tilgjengelig.",
        },
        "pl": {
            "settings": "Ustawienia",
            "timezone": "Strefa czasowa",
            "units": "Jednostka pogody",
            "celsius": "℃ Celsjusz",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Format czasu",
            "dst": "Automatyczny czas letni",
            "weather": "Lokalizacja pogody",
            "country": "Kraj / region",
            "all": "Wszystkie kraje / regiony",
            "more": "Więcej miast",
            "auto": "Automatycznie (IP)",
            "manual": "Wybierz miasto",
            "system": "Zgodnie z systemem",
            "search": "Szukaj",
            "back": "‹ Wstecz",
            "on": "Wł.",
            "off": "Wył.",
            "update": "Aktualizacja online",
            "unavailable": "Nie włączono",
            "version": "Wersja oprogramowania",
            "12": "12 godzin",
            "24": "24 godziny",
            "none": "Brak wyników.",
            "hint": "Szukaj miasta / regionu",
            "saving": "Zapisywanie…",
            "offline": "Wyświetlono miasta lokalne; wyszukiwanie online niedostępne.",
        },
        "pt": {
            "settings": "Definições",
            "timezone": "Fuso horário",
            "units": "Unidade meteorológica",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Formato da hora",
            "dst": "Hora de verão automática",
            "weather": "Localização meteorológica",
            "country": "País / região",
            "all": "Todos os países / regiões",
            "more": "Mais cidades",
            "auto": "Automático (IP)",
            "manual": "Escolher cidade",
            "system": "Seguir sistema",
            "search": "Pesquisar",
            "back": "‹ Voltar",
            "on": "Ligado",
            "off": "Desligado",
            "update": "Atualização online",
            "unavailable": "Não ativado",
            "version": "Versão do software",
            "12": "12 horas",
            "24": "24 horas",
            "none": "Sem resultados.",
            "hint": "Pesquisar cidade / região",
            "saving": "A guardar…",
            "offline": "Cidades locais mostradas; pesquisa online indisponível.",
        },
        "ro": {
            "settings": "Setări",
            "timezone": "Fus orar",
            "units": "Unitate meteo",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Format oră",
            "dst": "Ora de vară automată",
            "weather": "Locație meteo",
            "country": "Țară / regiune",
            "all": "Toate țările / regiunile",
            "more": "Mai multe orașe",
            "auto": "Automat (IP)",
            "manual": "Alege orașul",
            "system": "Urmează sistemul",
            "search": "Caută",
            "back": "‹ Înapoi",
            "on": "Pornit",
            "off": "Oprit",
            "update": "Actualizare online",
            "unavailable": "Neactivat",
            "version": "Versiune software",
            "12": "12 ore",
            "24": "24 de ore",
            "none": "Niciun rezultat.",
            "hint": "Caută oraș / regiune",
            "saving": "Se salvează…",
            "offline": "Orașele locale sunt afișate; căutarea online nu este disponibilă.",
        },
        "ru": {
            "settings": "Настройки",
            "timezone": "Часовой пояс",
            "units": "Единица погоды",
            "celsius": "℃ Цельсий",
            "fahrenheit": "℉ Фаренгейт",
            "format": "Формат времени",
            "dst": "Автоматическое летнее время",
            "weather": "Место погоды",
            "country": "Страна / регион",
            "all": "Все страны / регионы",
            "more": "Другие города",
            "auto": "Авто (IP)",
            "manual": "Выбрать город",
            "system": "По системе",
            "search": "Поиск",
            "back": "‹ Назад",
            "on": "Вкл.",
            "off": "Выкл.",
            "update": "Онлайн-обновление",
            "unavailable": "Не включено",
            "version": "Версия ПО",
            "12": "12 часов",
            "24": "24 часа",
            "none": "Нет результатов.",
            "hint": "Поиск города / региона",
            "saving": "Сохранение…",
            "offline": "Показаны местные города; онлайн-поиск недоступен.",
        },
        "es": {
            "settings": "Ajustes",
            "timezone": "Zona horaria",
            "units": "Unidad meteorológica",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Formato de hora",
            "dst": "Horario de verano automático",
            "weather": "Ubicación del clima",
            "country": "País / región",
            "all": "Todos los países / regiones",
            "more": "Más ciudades",
            "auto": "Automático (IP)",
            "manual": "Elegir ciudad",
            "system": "Seguir sistema",
            "search": "Buscar",
            "back": "‹ Atrás",
            "on": "Activado",
            "off": "Desactivado",
            "update": "Actualización en línea",
            "unavailable": "No activado",
            "version": "Versión del software",
            "12": "12 horas",
            "24": "24 horas",
            "none": "Sin resultados.",
            "hint": "Buscar ciudad / región",
            "saving": "Guardando…",
            "offline": "Se muestran ciudades locales; la búsqueda en línea no está disponible.",
        },
        "sv": {
            "settings": "Inställningar",
            "timezone": "Tidszon",
            "units": "Väder-enhet",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Tidsformat",
            "dst": "Automatisk sommartid",
            "weather": "Väderplats",
            "country": "Land / region",
            "all": "Alla länder / regioner",
            "more": "Fler städer",
            "auto": "Automatiskt (IP)",
            "manual": "Välj stad",
            "system": "Följ systemet",
            "search": "Sök",
            "back": "‹ Tillbaka",
            "on": "På",
            "off": "Av",
            "update": "Onlineuppdatering",
            "unavailable": "Inte aktiverad",
            "version": "Programvaruversion",
            "12": "12 timmar",
            "24": "24 timmar",
            "none": "Inga resultat.",
            "hint": "Sök stad / region",
            "saving": "Sparar…",
            "offline": "Lokala städer visas; onlinesökning är inte tillgänglig.",
        },
        "zh-tw": {
            "settings": "設定",
            "timezone": "時區",
            "units": "天氣單位",
            "celsius": "℃ 攝氏度",
            "fahrenheit": "℉ 華氏度",
            "format": "時間格式",
            "dst": "自動夏令時間",
            "weather": "天氣位置",
            "country": "國家／地區",
            "all": "全部國家／地區",
            "more": "更多城市",
            "auto": "自動定位（IP）",
            "manual": "手動選擇城市",
            "system": "跟隨系統",
            "search": "搜尋",
            "back": "‹ 返回",
            "on": "開",
            "off": "關",
            "update": "線上更新",
            "unavailable": "未啟用",
            "version": "軟體版本",
            "12": "12 小時制",
            "24": "24 小時制",
            "none": "沒有符合結果。",
            "hint": "搜尋城市／地區",
            "saving": "儲存中…",
            "offline": "已顯示本機城市；無法使用線上搜尋。",
        },
        "th": {
            "settings": "การตั้งค่า",
            "timezone": "เขตเวลา",
            "units": "หน่วยสภาพอากาศ",
            "celsius": "℃ เซลเซียส",
            "fahrenheit": "℉ ฟาเรนไฮต์",
            "format": "รูปแบบเวลา",
            "dst": "เวลาออมแสงอัตโนมัติ",
            "weather": "ตำแหน่งสภาพอากาศ",
            "country": "ประเทศ / ภูมิภาค",
            "all": "ทุกประเทศ / ภูมิภาค",
            "more": "เมืองเพิ่มเติม",
            "auto": "อัตโนมัติ (IP)",
            "manual": "เลือกเมือง",
            "system": "ตามระบบ",
            "search": "ค้นหา",
            "back": "‹ ย้อนกลับ",
            "on": "เปิด",
            "off": "ปิด",
            "update": "อัปเดตออนไลน์",
            "unavailable": "ไม่ได้เปิดใช้งาน",
            "version": "เวอร์ชันซอฟต์แวร์",
            "12": "12 ชั่วโมง",
            "24": "24 ชั่วโมง",
            "none": "ไม่พบผลลัพธ์",
            "hint": "ค้นหาเมือง / ภูมิภาค",
            "saving": "กำลังบันทึก…",
            "offline": "แสดงเมืองในเครื่อง ไม่สามารถค้นหาออนไลน์ได้",
        },
        "tr": {
            "settings": "Ayarlar",
            "timezone": "Saat dilimi",
            "units": "Hava birimi",
            "celsius": "℃ Celsius",
            "fahrenheit": "℉ Fahrenheit",
            "format": "Saat biçimi",
            "dst": "Otomatik yaz saati",
            "weather": "Hava konumu",
            "country": "Ülke / bölge",
            "all": "Tüm ülkeler / bölgeler",
            "more": "Daha fazla şehir",
            "auto": "Otomatik (IP)",
            "manual": "Şehir seç",
            "system": "Sistemi izle",
            "search": "Ara",
            "back": "‹ Geri",
            "on": "Açık",
            "off": "Kapalı",
            "update": "Çevrimiçi güncelleme",
            "unavailable": "Etkin değil",
            "version": "Yazılım sürümü",
            "12": "12 saat",
            "24": "24 saat",
            "none": "Sonuç yok.",
            "hint": "Şehir / bölge ara",
            "saving": "Kaydediliyor…",
            "offline": "Yerel şehirler gösteriliyor; çevrimiçi arama kullanılamıyor.",
        },
        "uk": {
            "settings": "Налаштування",
            "timezone": "Часовий пояс",
            "units": "Одиниця погоди",
            "celsius": "℃ Цельсій",
            "fahrenheit": "℉ Фаренгейт",
            "format": "Формат часу",
            "dst": "Автоматичний літній час",
            "weather": "Місце погоди",
            "country": "Країна / регіон",
            "all": "Усі країни / регіони",
            "more": "Інші міста",
            "auto": "Автоматично (IP)",
            "manual": "Вибрати місто",
            "system": "За системою",
            "search": "Пошук",
            "back": "‹ Назад",
            "on": "Увімк.",
            "off": "Вимк.",
            "update": "Онлайн-оновлення",
            "unavailable": "Не ввімкнено",
            "version": "Версія ПЗ",
            "12": "12 годин",
            "24": "24 години",
            "none": "Немає результатів.",
            "hint": "Пошук міста / регіону",
            "saving": "Збереження…",
            "offline": "Показано місцеві міста; онлайн-пошук недоступний.",
        },
        "vi": {
            "settings": "Cài đặt",
            "timezone": "Múi giờ",
            "units": "Đơn vị thời tiết",
            "celsius": "℃ Độ C",
            "fahrenheit": "℉ Độ F",
            "format": "Định dạng giờ",
            "dst": "Giờ mùa hè tự động",
            "weather": "Vị trí thời tiết",
            "country": "Quốc gia / khu vực",
            "all": "Tất cả quốc gia / khu vực",
            "more": "Thêm thành phố",
            "auto": "Tự động (IP)",
            "manual": "Chọn thành phố",
            "system": "Theo hệ thống",
            "search": "Tìm kiếm",
            "back": "‹ Quay lại",
            "on": "Bật",
            "off": "Tắt",
            "update": "Cập nhật trực tuyến",
            "unavailable": "Chưa bật",
            "version": "Phiên bản phần mềm",
            "12": "12 giờ",
            "24": "24 giờ",
            "none": "Không có kết quả.",
            "hint": "Tìm thành phố / khu vực",
            "saving": "Đang lưu…",
            "offline": "Đang hiển thị thành phố cục bộ; tìm kiếm trực tuyến không khả dụng.",
        },
    }
)


class DesktopPreferencesMixin:
    def _preferences_render(self, focus_key=None):
        focus = self.root.focus_get()
        cursor = focus.index("insert") if isinstance(focus, tk.Entry) else None
        focused_key = focus_key or getattr(self, "_preference_focus_id", "picker:back")
        selected_patch = None
        previous_list = getattr(self, "_preference_list", None)
        if focus_key is None and previous_list is not None and previous_list.winfo_exists():
            selected = previous_list.curselection()
            if selected and selected[0] < len(self._preference_choices):
                selected_patch = self._preference_choices[selected[0]][1]
        self._preferences_render_requested = True
        try:
            self._render()
        finally:
            self._preferences_render_requested = False
        if self._preference_picker:
            if selected_patch is not None:
                for index, (_, patch) in enumerate(self._preference_choices):
                    if patch == selected_patch:
                        self._preference_list.selection_clear(0, "end")
                        self._preference_list.selection_set(index)
                        self._preference_list.activate(index)
                        self._preference_list.see(index)
                        break
            self._focus_preference_control(focused_key)
            widget = self._control_widgets.get(self._preference_focus_id)
            if widget:
                if cursor is not None and isinstance(widget, tk.Entry):
                    widget.icursor(min(cursor, len(widget.get())))

    def _focus_preference_control(self, key):
        key = key if key in self._control_widgets else "picker:back"
        widget = self._control_widgets.get(key)
        if widget is not None:
            self._preference_focus_id = key
            widget.focus_set()
            self._refresh_preference_focus()

    def _refresh_preference_focus(self):
        if self._preference_picker not in ("timezone", "weather", "country"):
            return
        ui = sys.modules[type(self).__module__]
        for key, widget in self._control_widgets.items():
            if not key.startswith("picker:") or not widget.winfo_exists():
                continue
            focused = key == self._preference_focus_id
            default = getattr(widget, "_preference_background", ui.CARD_BG)
            if isinstance(widget, tk.Listbox):
                widget.configure(selectbackground=ui.PURPLE if focused else default)
            else:
                widget.configure(bg=ui.PURPLE if focused else default)
                if isinstance(widget, tk.Button):
                    widget.configure(
                        activebackground=ui.PURPLE if focused else default,
                        activeforeground=ui.WHITE,
                    )

    def _preference_focus_in(self, key):
        self._preference_focus_id = key
        self._refresh_preference_focus()

    def _pt(self, key):
        language = (
            self.language
            if self.language in TEXT
            else (
                "zh-tw"
                if self.language.startswith("zh-tw")
                else "zh" if self.language.startswith("zh") else "en"
            )
        )
        return TEXT.get(language, TEXT["en"]).get(key, TEXT["en"].get(key, key))

    def _init_preferences(self):
        self.display_preferences = dict(DEFAULTS)
        self._preference_options = {"zones": []}
        self._preference_picker = ""
        self._preference_focus_id = "picker:back"
        self._preference_query = ""
        self._preference_results = []
        self._preference_busy = False
        self._preference_generation = 0
        self._preference_country = ""
        self._preference_location_options = {"countries": [], "next_offset": None}
        self._preference_local_rows = []
        self._preference_message = ""
        self._settings_note_widget = None

    def _apply_preferences(self, settings):
        self.display_preferences.update(
            {
                key: value
                for key, value in settings.items()
                if key in DEFAULTS or key in ("display_preview", "weather_auto_city")
            }
        )

    def _preference_value(self, key):
        config = self.display_preferences
        if key == "timezone":
            name = config["display_timezone"]
            zone = (
                COMMON_ZONES.get(name, name.replace("_", " "))
                if name != "system"
                else self._pt("system")
            )
            return f'{zone} {config.get("display_preview", {}).get("offset", "")}'.strip()
        if key == "units":
            return self._pt(config["weather_temperature_unit"])
        if key == "format":
            return self._pt(config["display_time_format"])
        if key == "dst":
            return self._pt("on" if config["display_auto_dst"] else "off")
        city = config.get("weather_manual_location") or {}
        return (
            (city.get("name") or self._pt("manual"))
            if config["weather_location_mode"] == "manual"
            else f'{self._pt("auto")} · {config.get("weather_auto_city", "")}'
        )

    def _render_settings(self):
        ui = sys.modules[type(self).__module__]
        if self._content is None:
            return
        if self._preference_picker:
            self._render_preference_picker()
            return
        width = ui.CONTENT_W - ui._sx(90)
        x = ui._sx(45)
        row_height = ui._sy(64)
        for index, key in enumerate(
            ("timezone", "units", "format", "dst", "weather", "update", "version")
        ):
            y = ui._sy(58) + index * row_height
            label_text = self._pt(key)
            tk.Label(
                self._content,
                text=label_text,
                fg=ui.WHITE,
                bg=ui.BACKGROUND,
                font=self._fit_font(label_text, 230, 19),
                anchor="w",
            ).place(x=x + ui._sx(10), y=y, width=ui._sx(230), height=row_height)
            value = (
                self._preference_value(key)
                if index < 5
                else self._pt("unavailable") if key == "update" else ui.CURRENT_FW
            )
            if index < 5:
                button = tk.Button(
                    self._content,
                    text=value,
                    command=lambda selected=key: self._open_preference(selected),
                    bg=ui.BACKGROUND,
                    fg=ui.WHITE,
                    activebackground=ui.FOCUS_ROW_BG,
                    activeforeground=ui.WHITE,
                    relief="flat",
                    bd=0,
                    anchor="w",
                    font=self._fit_font(value, 305, 19),
                    highlightthickness=0,
                    takefocus=True,
                    state="disabled" if self._preference_busy else "normal",
                )
                button.place(
                    x=x + ui._sx(245),
                    y=y + ui._sy(6),
                    width=width - ui._sx(245),
                    height=row_height - ui._sy(12),
                )
                self._control_widgets[f"settings:{key}"] = button
            else:
                tk.Label(
                    self._content,
                    text=value,
                    bg=ui.BACKGROUND,
                    fg=ui.MUTED,
                    anchor="w",
                    font=self._font(19),
                ).place(x=x + ui._sx(245), y=y, width=width - ui._sx(245), height=row_height)
            # Draw the separator after the row controls so opaque Tk labels do
            # not cover the line. This keeps all seven rows continuous,
            # including Online Update and Software Version.
            divider = tk.Frame(self._content, bg=ui.CONTROL_DIVIDER)
            divider.place(x=x, y=y + row_height - 1, width=width, height=1)
            divider.lift()
        self._create_action_bar()
        self._settings_note_widget = tk.Label(
            self._content,
            text=self._settings_note_text(),
            fg=ui.MUTED,
            bg=ui.BACKGROUND,
            font=self._font(15),
        )
        self._settings_note_widget.place(
            x=x, y=ui.WINDOW_H - ui.ACTION_BAR_H + ui._sy(30), width=width, height=ui._sy(35)
        )

    def _settings_note_text(self):
        preview = self.display_preferences.get("display_preview", {})
        return (
            self._pt("saving") if self._preference_busy else f'{
                preview.get(
                    "clock",
                    "")} {
                preview.get(
                    "ampm",
                    "")}  {
                        preview.get(
                            "offset",
                            "")}').strip()

    def _refresh_settings(self):
        """Keep the page and input targets alive during saves and status events."""
        if self.section != "settings" or self._preference_picker:
            return False
        note = self._settings_note_widget
        controls = [
            (key, self._control_widgets.get(f"settings:{key}"))
            for key in ("timezone", "units", "format", "dst", "weather")
        ]
        if (
            note is None
            or not note.winfo_exists()
            or any(widget is None or not widget.winfo_exists() for _, widget in controls)
        ):
            return False
        ui = sys.modules[type(self).__module__]
        for key, widget in controls:
            value = self._preference_value(key)
            focused = (
                self._navigation.region == "content"
                and self._navigation.control == f"settings:{key}"
            )
            values = {
                "state": "disabled" if self._preference_busy else "normal",
                "highlightthickness": 3 if focused else 0,
                "highlightbackground": ui.PURPLE,
                "highlightcolor": ui.PURPLE,
            }
            changed = {
                option: value
                for option, value in values.items()
                if str(widget.cget(option)) != str(value)
            }
            if str(widget.cget("text")) != value:
                changed.update(text=value, font=self._fit_font(value, 305, 19))
            if changed:
                widget.configure(**changed)
        value = self._settings_note_text()
        if str(note.cget("text")) != value:
            note.configure(text=value)
        return True

    def _open_preference(self, key):
        if self._preference_busy:
            return
        if key == "dst":
            self._save_preference(
                {"display_auto_dst": not self.display_preferences["display_auto_dst"]}
            )
            return
        if key == "units":
            current = self.display_preferences.get("weather_temperature_unit", "celsius")
            self._save_preference(
                {"weather_temperature_unit": "fahrenheit" if current == "celsius" else "celsius"}
            )
            return
        if key == "format":
            current = str(self.display_preferences.get("display_time_format", "24"))
            self._save_preference({"display_time_format": "12" if current == "24" else "24"})
            return
        self._preference_picker = key
        self._preference_query = ""
        self._preference_results = []
        self._preference_generation += 1
        self._preference_message = ""
        if key == "weather":
            self._preference_location_options = self._preference_options.get(
                "weather_locations", {"countries": [], "next_offset": None}
            )
            self._preference_country = self._preference_location_options.get("country_code", "")
            self._preference_local_rows = list(self._preference_location_options.get("cities", []))
        self._preferences_render(
            focus_key="picker:input" if key in ("timezone", "weather") else "picker:back"
        )
        if key == "weather":
            self._load_preference_cities()
        if key == "timezone" and not self._preference_options.get("zones"):
            generation = self._preference_generation
            self._run_task(
                self._pt("timezone"),
                self.backend.get_display_options,
                lambda value: self._received_options(value, generation),
            )

    def _received_options(self, value, generation):
        self._preference_options = value
        if generation == self._preference_generation and self._preference_picker == "timezone":
            self._preferences_render()

    def _close_preference_picker(self):
        selected = self._preference_picker
        if selected == "country":
            self._preference_picker = "weather"
            self._preference_query = ""
            self._preference_generation += 1
            self._preferences_render(focus_key="picker:country")
            self._load_preference_cities()
            return
        self._preference_picker = ""
        self._preference_generation += 1
        from desktop_controller import DesktopNavigationState

        self._navigation = DesktopNavigationState(
            region="content", control=f"settings:{selected}", section="settings"
        )
        self._preferences_render()

    def _render_preference_picker(self):
        ui = sys.modules[type(self).__module__]
        kind = self._preference_picker
        x, width = ui._sx(30), ui.CONTENT_W - ui._sx(60)
        back = tk.Button(
            self._content,
            text=self._pt("back"),
            command=self._close_preference_picker,
            bg=ui.BACKGROUND,
            fg=ui.WHITE,
            activebackground=ui.FOCUS_ROW_BG,
            activeforeground=ui.WHITE,
            relief="flat",
            font=self._font(17),
            bd=0,
        )
        back.place(x=x, y=ui._sy(15), width=ui._sx(100), height=ui._sy(40))
        self._control_widgets["picker:back"] = back
        tk.Label(
            self._content, text=self._pt(kind), bg=ui.BACKGROUND, fg=ui.WHITE, font=self._font(20)
        ).place(x=x + ui._sx(120), y=ui._sy(15), width=width - ui._sx(130), height=ui._sy(40))
        start = ui._sy(70)
        if kind in ("timezone", "weather", "country"):
            entry = tk.Entry(
                self._content,
                bg=ui.CARD_BG,
                fg=ui.WHITE,
                insertbackground=ui.WHITE,
                font=self._font(16),
                relief="flat",
            )
            entry.insert(0, self._preference_query)
            entry.place(x=x, y=start, width=width - ui._sx(100), height=ui._sy(38))
            self._preference_entry = entry
            self._control_widgets["picker:input"] = entry
            entry.bind(
                "<KeyRelease>",
                lambda event: self._update_preference_query(entry.get(), event.keysym),
            )
            entry.bind("<Return>", lambda event: (self._search_preference(), "break")[1])
            search = tk.Button(
                self._content,
                text=self._pt("search"),
                command=self._search_preference,
                bg=ui.BUTTON_BG,
                fg=ui.WHITE,
                relief="flat",
                font=self._font(15),
            )
            search.place(x=x + width - ui._sx(92), y=start, width=ui._sx(92), height=ui._sy(38))
            self._control_widgets["picker:search"] = search
            start += ui._sy(50)
        if kind == "weather":
            selected_country = next(
                (
                    item
                    for item in self._preference_location_options.get("countries", [])
                    if item["code"] == self._preference_country
                ),
                None,
            )
            name = (
                (
                    selected_country.get("name_zh")
                    if self.language.startswith("zh")
                    else selected_country.get("name")
                )
                if selected_country
                else self._pt("all")
            )
            country = tk.Button(
                self._content,
                text=f'{self._pt("country")}: {name} ▾',
                command=self._open_preference_country,
                bg=ui.CARD_BG,
                fg=ui.WHITE,
                activebackground=ui.FOCUS_ROW_BG,
                relief="flat",
                anchor="w",
                font=self._font(16),
            )
            country.place(x=x, y=start, width=width, height=ui._sy(36))
            self._control_widgets["picker:country"] = country
            start += ui._sy(46)
        self._preference_list = tk.Listbox(
            self._content,
            bg=ui.CARD_BG,
            fg=ui.WHITE,
            selectbackground=ui.PURPLE,
            selectforeground=ui.WHITE,
            exportselection=False,
            font=self._font(16),
            bd=0,
            highlightthickness=0,
            activestyle="none",
        )
        self._preference_list.place(
            x=x, y=start, width=width - ui._sx(15), height=ui.WINDOW_H - start - ui._sy(100)
        )
        scroll = tk.Scrollbar(self._content, command=self._preference_list.yview)
        scroll.place(
            x=x + width - ui._sx(15),
            y=start,
            width=ui._sx(15),
            height=ui.WINDOW_H - start - ui._sy(100),
        )
        self._preference_list.configure(yscrollcommand=scroll.set)
        self._preference_list.bind(
            "<ButtonRelease-1>", lambda event: self._select_preference_item()
        )
        self._preference_list.bind("<Return>", lambda event: self._select_preference_item())
        self._control_widgets["picker:list"] = self._preference_list
        self._populate_preference_list()
        if kind == "weather" and self._preference_location_options.get("next_offset") is not None:
            more = tk.Button(
                self._content,
                text=self._pt("more"),
                command=lambda: self._load_preference_cities(
                    self._preference_location_options["next_offset"]
                ),
                bg=ui.BUTTON_BG,
                fg=ui.WHITE,
                relief="flat",
                font=self._font(15),
            )
            more.place(x=x, y=ui.WINDOW_H - ui._sy(90), width=width, height=ui._sy(32))
            self._control_widgets["picker:more"] = more
        tk.Label(
            self._content,
            text=self._preference_message
            or (self._pt("hint") if kind not in ("format", "units") else ""),
            fg=ui.MUTED,
            bg=ui.BACKGROUND,
            font=self._font(12),
        ).place(x=x, y=ui.WINDOW_H - ui._sy(52), width=width, height=ui._sy(30))
        if kind in ("timezone", "weather", "country"):
            for key, widget in self._control_widgets.items():
                if not key.startswith("picker:"):
                    continue
                widget._preference_background = widget.cget("bg")
                widget.bind(
                    "<FocusIn>",
                    lambda event, target=key: self._preference_focus_in(target),
                    add="+",
                )
                widget.bind(
                    "<ButtonPress-1>",
                    lambda event, target=key: self._focus_preference_control(target),
                    add="+",
                )
                # Consume vertical keys before Tk's Listbox class binding can
                # move once, followed by a second move from the app queue.
                for keysym, action in (("Up", "up"), ("Down", "down")):
                    widget.bind(
                        f"<{keysym}>",
                        lambda event, direction=action: self._queue_controller_action(direction),
                    )
            self._preference_list.bind(
                "<Return>", lambda event: (self._select_preference_item(), "break")[1]
            )

    def _city_label(self, item):
        name = (
            item.get("name_zh")
            if self.language.startswith("zh") and item.get("name_zh")
            else item.get("name", "")
        )
        country = item.get("country") or item.get("country_code", "")
        return " · ".join(value for value in (name, item.get("admin1", ""), country) if value)

    def _populate_preference_list(self):
        selected = self._preference_list.curselection()
        old_choices = getattr(self, "_preference_choices", [])
        selected_patch = (
            old_choices[selected[0]][1] if selected and selected[0] < len(old_choices) else None
        )
        kind, query = self._preference_picker, self._preference_query.lower()
        if kind == "units":
            self._preference_choices = [
                (self._pt(value), {"weather_temperature_unit": value})
                for value in ("celsius", "fahrenheit")
            ]
        elif kind == "format":
            self._preference_choices = [
                (self._pt(value), {"display_time_format": value}) for value in ("24", "12")
            ]
        elif kind == "country":
            self._preference_choices = [(self._pt("all"), {"_country": "ALL"})]
            for item in self._preference_location_options.get("countries", []):
                label = item["name_zh"] if self.language.startswith("zh") else item["name"]
                if query in (label + " " + item["name"] + " " + item["code"]).lower():
                    self._preference_choices.append((label, {"_country": item["code"]}))
        elif kind == "timezone":
            self._preference_choices = [(self._pt("system"), {"display_timezone": "system"})]
            self._preference_choices += [
                (f'{item["label"]} {item["offset"]}', {"display_timezone": item["id"]})
                for item in self._preference_options.get("zones", [])
                if query in (item["label"] + " " + item["id"]).lower()
            ]
        else:
            self._preference_choices = [(self._pt("auto"), {"weather_location_mode": "auto"})]
            recent = (
                self.display_preferences.get("weather_recent_locations", []) if not query else []
            )
            items = recent + self._preference_results + self._preference_local_rows
            seen = set()
            for item in items:
                if (
                    self._preference_country
                    and self._preference_country != "ALL"
                    and item.get("country_code") != self._preference_country
                ):
                    continue
                label = self._city_label(item)
                if (
                    query
                    and query
                    not in (
                        label + " " + item.get("name_en", "") + " " + item.get("name", "")
                    ).lower()
                ):
                    continue
                point = (item.get("latitude"), item.get("longitude"))
                if point in seen:
                    continue
                seen.add(point)
                location = {
                    **item,
                    "name": (
                        item.get("name_zh")
                        if self.language.startswith("zh") and item.get("name_zh")
                        else item["name"]
                    ),
                }
                self._preference_choices.append(
                    (
                        label,
                        {"weather_location_mode": "manual", "weather_manual_location": location},
                    )
                )
        self._preference_list.delete(0, "end")
        for label, _ in self._preference_choices:
            self._preference_list.insert("end", label)
        if self._preference_choices:
            index = next(
                (
                    i
                    for i, (_, patch) in enumerate(self._preference_choices)
                    if patch == selected_patch
                ),
                0,
            )
            self._preference_list.selection_set(index)
            self._preference_list.activate(index)

    def _open_preference_country(self):
        self._preference_picker = "country"
        self._preference_query = ""
        self._preference_generation += 1
        self._preferences_render(focus_key="picker:input")

    def _load_preference_cities(self, offset=0, online=False):
        self._preference_generation += 1
        generation, country, query = (
            self._preference_generation,
            self._preference_country,
            self._preference_query,
        )
        self._run_task(
            self._pt("weather"),
            lambda: self.backend.get_weather_location_options(
                country, query, offset, 40, self.language
            ),
            lambda value: self._received_location_options(value, generation, offset, online),
            lambda error: self._received_city_error(error, generation),
        )

    def _received_location_options(self, value, generation, offset=0, online=False):
        if generation != self._preference_generation or self._preference_picker != "weather":
            return
        self._preference_country = value["country_code"]
        self._preference_location_options = value
        self._preference_local_rows = (self._preference_local_rows if offset else []) + value[
            "cities"
        ]
        self._preference_results = []
        self._preferences_render()
        if offset and value["cities"]:
            new_points = {(item["latitude"], item["longitude"]) for item in value["cities"]}
            index = next(
                (
                    index
                    for index, (_, patch) in enumerate(self._preference_choices)
                    if (
                        patch.get("weather_manual_location", {}).get("latitude"),
                        patch.get("weather_manual_location", {}).get("longitude"),
                    )
                    in new_points
                ),
                0,
            )
            self._preference_list.selection_clear(0, "end")
            self._preference_list.selection_set(index)
            self._preference_list.see(index)
            self._focus_preference_control("picker:list")
        if online and len(self._preference_query.strip()) >= 2:
            query, country = self._preference_query, self._preference_country
            self._run_task(
                self._pt("search"),
                lambda: self.backend.search_weather_locations(query, self.language, country),
                lambda rows: self._received_cities(rows, generation),
                lambda error: self._received_city_error(error, generation),
            )

    def _update_preference_query(self, query, key=""):
        if query == self._preference_query:
            return
        if query != self._preference_query and self._preference_picker == "weather":
            self._preference_generation += 1
            self._preference_results = []
        self._preference_query = query
        if self._preference_picker in ("timezone", "weather", "country"):
            self._populate_preference_list()

    def _search_preference(self):
        self._preference_query = self._preference_entry.get().strip()
        if self._preference_picker != "weather":
            self._populate_preference_list()
            return
        self._preference_message = ""
        self._load_preference_cities(online=True)

    def _received_city_error(self, error, generation):
        if generation == self._preference_generation and self._preference_picker == "weather":
            if self._preference_local_rows:
                self._preference_message = self._pt("offline")
                self._preferences_render()
            else:
                messagebox.showerror(self._pt("weather"), str(error))

    def _received_cities(self, value, generation):
        if generation != self._preference_generation or self._preference_picker != "weather":
            return
        self._preference_results = value
        self._populate_preference_list()
        if not value and not self._preference_local_rows:
            from tkinter import messagebox

            messagebox.showinfo(self._pt("weather"), self._pt("none"))

    def _select_preference_item(self):
        selected = self._preference_list.curselection()
        if selected:
            update = self._preference_choices[selected[0]][1]
            if "_country" in update:
                self._preference_country = update["_country"]
                self._preference_picker = "weather"
                self._preference_query = ""
                self._preference_results = []
                self._preference_local_rows = []
                self._load_preference_cities()
            else:
                self._save_preference(update)

    def _save_preference(self, update):
        if self._preference_busy:
            return
        self._preference_busy = True
        self._preferences_render()

        def save():
            self.backend.save_settings(update)
            return self.backend.get_control_state()

        def done(snapshot):
            self._preference_busy = False
            self._apply_control_state(snapshot)
            if self._preference_picker:
                self._close_preference_picker()
            elif self.section == "settings":
                # The WebSocket may already have delivered this revision while
                # saving. Always release the controls even if it is deduplicated.
                self._preferences_render()

        def failed(error):
            self._preference_busy = False
            self._preferences_render()
            from tkinter import messagebox

            messagebox.showerror(self._pt("settings"), str(error))

        self._run_task(self._pt("settings"), save, done, failed)

    def _handle_preference_action(self, action):
        if not self._preference_picker or self._navigation.exit_confirming:
            return False
        if action == "back":
            self._close_preference_picker()
            return True
        controls = [
            key
            for key in (
                "picker:back",
                "picker:input",
                "picker:search",
                "picker:country",
                "picker:list",
                "picker:more",
            )
            if key in self._control_widgets
        ]
        current = getattr(self, "_preference_focus_id", "picker:back")
        if self._preference_picker not in ("timezone", "weather", "country"):
            focus = self.root.focus_get()
            current = next(
                (key for key in controls if self._control_widgets[key] == focus), "picker:back"
            )
        if current not in controls:
            current = controls[0]
        if current == "picker:list" and action in ("up", "down"):
            selected = self._preference_list.curselection()
            index = selected[0] if selected else 0
            if action == "up" and index == 0:
                self._focus_preference_control(
                    "picker:country"
                    if "picker:country" in controls
                    else "picker:input" if "picker:input" in controls else "picker:back"
                )
            elif (
                action == "down"
                and index == len(self._preference_choices) - 1
                and "picker:more" in controls
            ):
                self._focus_preference_control("picker:more")
            else:
                index = max(
                    0,
                    min(len(self._preference_choices) - 1, index + (1 if action == "down" else -1)),
                )
                self._preference_list.selection_clear(0, "end")
                self._preference_list.selection_set(index)
                self._preference_list.activate(index)
                self._preference_list.see(index)
            return True
        if action == "activate":
            if current == "picker:list":
                self._select_preference_item()
            elif current in ("picker:search", "picker:back", "picker:country", "picker:more"):
                self._control_widgets[current].invoke()
            else:
                self._focus_preference_control(current)
            return True
        if action in ("up", "down", "left", "right"):
            if self._preference_picker in ("timezone", "weather", "country"):
                below_search = "picker:country" if "picker:country" in controls else "picker:list"
                targets = {
                    "picker:back": {"down": "picker:input"},
                    "picker:input": {
                        "up": "picker:back",
                        "down": below_search,
                        "right": "picker:search",
                    },
                    "picker:search": {
                        "up": "picker:back",
                        "down": below_search,
                        "left": "picker:input",
                    },
                    "picker:country": {"up": "picker:input", "down": "picker:list"},
                    "picker:more": {"up": "picker:list"},
                }
                self._focus_preference_control(targets.get(current, {}).get(action, current))
                return True
            index = controls.index(current)
            target = max(
                0, min(len(controls) - 1, index + (1 if action in ("down", "right") else -1))
            )
            self._focus_preference_control(controls[target])
            return True
        return True
