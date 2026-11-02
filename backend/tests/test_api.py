"""End-to-end API tests with the mock LLM and a fake vehicle catalog.

Run:  cd backend && pytest -q
"""

import os
import tempfile

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{tmp}/uploads"
os.environ["LLM_PROVIDER"] = "mock"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-at-least-32-bytes-long"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas import VinDecodeOut  # noqa: E402
from app.services import catalog, vehicle_reports  # noqa: E402

# 1x1 transparent PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082"
)


@pytest.fixture(autouse=True)
def no_nhtsa(monkeypatch):
    async def fake_reports(make, model, year):
        return None

    monkeypatch.setattr(vehicle_reports, "get_vehicle_reports", fake_reports)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def auth(client):
    r = client.post("/api/auth/register", json={"email": "test@example.com", "password": "secret123", "language": "en"})
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_auth_flow(client, auth):
    assert client.get("/api/auth/me", headers=auth).json()["email"] == "test@example.com"
    assert client.post("/api/auth/login", json={"email": "test@example.com", "password": "wrong-pass"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "TEST@example.com", "password": "secret123"}).status_code == 200
    assert client.get("/api/vehicles").status_code == 401


def test_vin_decode(client, auth, monkeypatch):
    async def fake_decode(vin):
        return VinDecodeOut(vin=vin, make="Toyota", model="Camry", year=2018, engine="2.5L I4")

    monkeypatch.setattr(catalog, "decode_vin", fake_decode)
    assert client.get("/api/catalog/vin/4T1B11HK5JU123456").status_code == 401
    r = client.get("/api/catalog/vin/4T1B11HK5JU123456", headers=auth)
    assert r.status_code == 200 and r.json()["model"] == "Camry"
    assert client.get("/api/catalog/vin/TOO-SHORT", headers=auth).status_code == 422


def test_vin17_fallback(monkeypatch):
    """A VIN vPIC only half-decodes (make, no model) goes to 17VIN; Chinese-only fields are dropped."""
    import asyncio

    from app.services import vin17

    async def vpic_partial(vin):
        return VinDecodeOut(vin=vin, make="Peugeot")

    signed = []

    async def fake_call(path, params):
        signed.append(f"{path}?vin={params['vin']}")
        # Shape of a real 3001 answer: Chinese fields + *_en twins, and the exact factory entry
        return {"model_year_from_vin": "2017", "epc": "peugeot", "epc_id": "42", "matching_mode": "exact_match",
                "brand": "标致", "made_in_en": "France",
                "model_list": [{"Brand": "标致", "Brand_en": "Peugeot", "Model": "3008", "Model_en": "3008",
                                "Model_year": "2017", "Cc": "1.6L", "Cc_en": "1.6L", "Air_intake_en": "Turbo",
                                "Engine_no_en": "EP6FDT", "Fuel_type": "汽油", "Fuel_type_en": "gas",
                                "Gear_num_en": "6", "Transmission_detail_en": "automatic(AT)",
                                "Body_type_en": "SUV", "Img_adress": "a.jpg,b.jpg"}] * 2,
                "model_original_epc_list": [{"CarAttributes": [
                    {"Language": "zh", "Col_name": "级别", "Col_value": "高级"},
                    {"Language": "en", "Col_name": "Grade", "Col_value": "Allure"},
                    {"Language": "en", "Col_name": "ATM/MTM", "Col_value": "ATM"}]}]}

    monkeypatch.setattr(catalog, "_decode_vpic", vpic_partial)
    monkeypatch.setattr(vin17, "enabled", lambda: True)
    monkeypatch.setattr(vin17, "call", fake_call)
    vin17._cache.clear()

    r = asyncio.run(catalog.decode_vin("vf3mcbhzhhs123456"))
    assert (r.make, r.model, r.year) == ("Peugeot", "3008", 2017)
    assert r.engine == "1.6L Turbo (EP6FDT)" and r.transmission == "automatic" and r.fuel_type == "gasoline"
    assert (r.trim, r.body_class, r.plant_country, r.warnings) == ("Allure", "SUV", "France", [])
    assert r.raw["epc"] == "peugeot" and r.raw["source"] == "17vin" and len(r.raw["images"]) == 2
    assert signed == ["/?vin=VF3MCBHZHHS123456"]

    # Same signing as the doc example: md5(md5(user) + md5(password) + "/?vin=...")
    import hashlib
    md5 = lambda t: hashlib.md5(t.encode()).hexdigest()  # noqa: E731
    from app.config import get_settings
    s = get_settings()
    assert vin17.sign("/?vin=X") == md5(md5(s.vin17_user) + md5(s.vin17_password) + "/?vin=X")


def test_vehicle_and_chat(client, auth):
    r = client.post("/api/vehicles", headers=auth, json={
        "make": "Kia", "model": "Sportage", "year": 2016, "engine": "2.0L I4",
        "mileage_km": 145000, "source": "catalog",
    })
    assert r.status_code == 201, r.text
    vehicle = r.json()
    assert vehicle["display_name"] == "2016 Kia Sportage"

    conv = client.post(f"/api/vehicles/{vehicle['id']}/conversations", headers=auth).json()

    r = client.post(f"/api/conversations/{conv['id']}/messages", headers=auth,
                    data={"text": "Check engine light is on and the car shakes at idle"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Sportage" in body["assistant_message"]["content"]
    assert body["conversation"]["title"].startswith("Check engine light")

    r = client.post(f"/api/conversations/{conv['id']}/messages", headers=auth,
                    data={"text": "here is a photo"}, files={"image": ("engine.png", PNG, "image/png")})
    assert r.status_code == 200, r.text
    image_url = r.json()["user_message"]["image_url"]
    assert image_url and client.get(image_url).status_code == 200

    detail = client.get(f"/api/conversations/{conv['id']}", headers=auth).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]

    assert client.post(f"/api/conversations/{conv['id']}/messages", headers=auth, data={"text": "  "}).status_code == 422


def test_other_user_cannot_see_vehicle(client, auth):
    vid = client.get("/api/vehicles", headers=auth).json()[0]["id"]
    r = client.post("/api/auth/register", json={"email": "other@example.com", "password": "secret123"})
    other = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert client.get(f"/api/vehicles/{vid}", headers=other).status_code == 404


def test_vehicle_reports_section():
    recalls = {"results": [{
        "NHTSACampaignNumber": "18V907000", "ReportReceivedDate": "19/12/2018", "parkIt": False,
        "Component": "FUEL SYSTEM, GASOLINE", "Summary": "The fuel pipe may leak.",
        "Consequence": "Risk of fire.", "Remedy": "Dealers will replace the pipe free of charge.",
    }]}
    complaints = {"results": [
        {"components": "ENGINE", "summary": "Engine seized at 90k miles.", "fire": False},
        {"components": "ENGINE,ELECTRICAL SYSTEM", "summary": "Engine fire.", "fire": True},
        {"components": "STEERING", "summary": "Steering locks.", "crash": True, "numberOfInjuries": 1},
    ]}
    reports = vehicle_reports.VehicleReports(recalls=vehicle_reports.parse_recalls(recalls))
    vehicle_reports.summarize_complaints(complaints, reports)

    assert reports.complaint_count == 3
    assert reports.top_components[0] == ("ENGINE", 2)
    assert (reports.crashes, reports.fires, reports.injuries) == (1, 1, 1)

    section = vehicle_reports.reports_section(reports)
    assert "18V907000" in section and "ENGINE: 2 complaints" in section
    assert vehicle_reports.reports_section(None) == ""


def test_obd_extract_and_lookup():
    from app.services import obd

    assert obd.extract_codes("Scanner says p0171, P 0174 and P0171 again; my VIN ends 1P0300X") == ["P0171", "P0174"]
    assert obd.lookup("P0420").definition.startswith("Catalyst System Efficiency")
    assert obd.lookup("P0304").definition == "Cylinder 4 Misfire Detected"
    assert "Ignition Coil" in obd.lookup("P0352").definition
    maker = obd.lookup("P1456")
    assert not maker.generic and maker.definition is None and maker.subsystem and maker.source is None
    section = obd.codes_section(["P0300", "P1456"], [])
    assert "Random/Multiple Cylinder Misfire" in section and "MANUFACTURER-SPECIFIC" in section


def test_obd_obdex_enrichment():
    from app.services import obd

    lean = obd.lookup("P0171")
    assert lean.source == "obdex" and lean.severity == "medium"  # OBDex data + our severity
    assert lean.causes and lean.symptoms and "P0174" in lean.related
    section = obd.codes_section(["P0171"], [])
    assert "Common causes" in section and "Typical symptoms" in section


def test_obd_endpoint(client):
    r = client.get("/api/obd/p0300")
    body = r.json()
    assert r.status_code == 200 and body["severity"] == "high"
    assert body["source"] == "obdex" and body["credit"] and body["causes"][0]["likelihood"]
    assert client.get("/api/obd/hello").status_code == 422


def test_obd_codes_remembered_per_car(client, auth):
    from app.db import SessionLocal
    from app.models import ObdReading

    vid = client.get("/api/vehicles", headers=auth).json()[0]["id"]
    c1 = client.post(f"/api/vehicles/{vid}/conversations", headers=auth).json()
    client.post(f"/api/conversations/{c1['id']}/messages", headers=auth, data={"text": "Code P0420 and p0420"})
    c2 = client.post(f"/api/vehicles/{vid}/conversations", headers=auth).json()
    client.post(f"/api/conversations/{c2['id']}/messages", headers=auth, data={"text": "Now P0171"})

    with SessionLocal() as db:
        codes = [(r.conversation_id, r.code) for r in db.query(ObdReading).filter_by(vehicle_id=vid)]
    assert codes == [(c1["id"], "P0420"), (c2["id"], "P0171")]


def test_epa_specs_and_prompt():
    from app.services import epa
    from app.services.prompts import specs_summary

    specs = epa.parse_specs({
        "id": "36800", "model": "Corolla", "trany": "Automatic (AV-S7)", "drive": "Front-Wheel Drive",
        "displ": "1.8", "cylinders": "4", "fuelType1": "Regular Gasoline", "comb08": "31", "city08": "28",
        "highway08": "36", "tCharger": "", "startStop": "N",
    })
    assert specs["engine"] == "1.8L 4 cyl" and specs["l_100km_combined"] == 7.6 and "turbo" not in specs
    assert "CVT" in specs_summary(specs) and "7.6 L/100 km" in specs_summary(specs)


def test_canada_and_uk_recalls(monkeypatch):
    detail = {"ResultSet": [[
        {"Name": "SYSTEM_TYPE_ETXT", "Value": {"Literal": "Airbag"}},
        {"Name": "NOTIFICATION_TYPE_ETXT", "Value": {"Literal": "Safety Mfr"}},
        {"Name": "COMMENT_ETXT", "Value": {"Literal": "The airbag module could be damaged."}},
    ]]}
    ca = vehicle_reports.parse_canada_recall("2020013", "1/17/2020 12:00:00 AM", detail)
    assert (ca.date, ca.system, ca.kind) == ("2020-01-17", "Airbag", "Safety Mfr")

    monkeypatch.setattr(vehicle_reports, "_uk_index", lambda: {"peugeot": [
        {"ref": "R/2019/001", "models": "208, 2008", "defect": "Brake hose", "build_start_year": 2015, "build_end_year": 2017},
        {"ref": "R/2021/002", "models": "3008", "defect": "Seat belt", "build_start_year": 2019, "build_end_year": 2020},
    ]})
    assert [r.ref for r in vehicle_reports.uk_recalls_for("Peugeot", "208", 2016)] == ["R/2019/001"]
    assert vehicle_reports.uk_recalls_for("Peugeot", "208", 2022) == []      # outside build years
    assert vehicle_reports.uk_recalls_for("Peugeot", "308", 2016) == []      # "308" must not match "3008"

    reports = vehicle_reports.VehicleReports(
        recalls_canada=[ca], recalls_uk=vehicle_reports.uk_recalls_for("Peugeot", "208", 2016),
        safety=vehicle_reports.SafetyRating("2016 Peugeot 208", "5", "5", "5", "4"),
    )
    section = vehicle_reports.reports_section(reports)
    assert "TC 2020013" in section and "DVSA R/2019/001" in section and "overall 5/5" in section


def test_vehicle_with_exact_version_and_reports(client, auth, monkeypatch):
    from app.services import epa

    async def fake_specs(epa_id):
        return {"epa_id": epa_id, "engine": "1.8L 4 cyl", "transmission": "Automatic (AV-S7)"}

    monkeypatch.setattr(epa, "get_specs", fake_specs)
    r = client.post("/api/vehicles", headers=auth, json={
        "make": "Toyota", "model": "Corolla", "year": 2016, "source": "catalog", "epa_id": 36800,
    })
    assert r.status_code == 201, r.text
    car = r.json()
    assert car["specs"]["transmission"] == "Automatic (AV-S7)" and car["engine"] == "1.8L 4 cyl"

    # NHTSA is faked as unreachable in tests
    assert client.get(f"/api/vehicles/{car['id']}/reports", headers=auth).json() == {
        "available": False, "recalls_us": 0, "recalls_canada": 0, "recalls_uk": 0, "complaints": 0, "safety": None,
        "recalls": [], "top_components": [], "crashes": 0, "fires": 0, "injuries": 0,
    }

    # With data: recalls of all markets merged newest first, complaints by component with examples
    reports = vehicle_reports.VehicleReports(
        recalls=vehicle_reports.parse_recalls({"results": [{
            "NHTSACampaignNumber": "20V024000", "ReportReceivedDate": "17/01/2020", "Summary": "Airbag may not deploy.",
            "parkIt": True,
        }]}),
        recalls_canada=[vehicle_reports.CanadaRecall("2021001", "2021-03-02", "Brakes", "Safety Mfr", "Brake line")],
    )
    vehicle_reports.summarize_complaints({"results": [{"components": "ENGINE", "summary": "Oil leak."}]}, reports)

    async def fake_reports(make, model, year):
        return reports

    monkeypatch.setattr(vehicle_reports, "get_vehicle_reports", fake_reports)
    body = client.get(f"/api/vehicles/{car['id']}/reports", headers=auth).json()
    assert [(r["market"], r["ref"], r["date"]) for r in body["recalls"]] == [
        ("CA", "2021001", "2021-03-02"), ("US", "20V024000", "2020-01-17"),
    ]
    assert body["recalls"][1]["park_it"] is True
    assert body["top_components"] == [{"component": "ENGINE", "count": 1, "examples": ["Oil leak."]}]


def test_vin_from_photo(client, auth, monkeypatch):
    from app.services import vin_photo

    # Misread O/I fixed; the engine number next to it is ignored; check digit picks the right candidate
    assert vin_photo.parse_vin("2T1BURHE8GC6O3523") == "2T1BURHE8GC603523"
    assert vin_photo.parse_vin("VIN: 1HGCM 82633A004352") == "1HGCM82633A004352"
    assert vin_photo.parse_vin("NONE") is None
    assert vin_photo.check_digit_ok("1HGCM82633A004352") and not vin_photo.check_digit_ok("1HGCM82643A004352")

    # Mock LLM returns a demo VIN
    r = client.post("/api/catalog/vin-photo", headers=auth, files={"image": ("card.png", PNG, "image/png")})
    assert r.status_code == 200 and r.json() == {"vin": "1HGCM82633A004352"}

    assert client.post("/api/catalog/vin-photo", files={"image": ("card.png", PNG, "image/png")}).status_code == 401
    r = client.post("/api/catalog/vin-photo", headers=auth, files={"image": ("a.txt", b"hi", "text/plain")})
    assert r.status_code == 415

    async def no_vin(image, mime):
        return None

    monkeypatch.setattr(vin_photo, "read_vin", no_vin)
    r = client.post("/api/catalog/vin-photo", headers=auth, files={"image": ("card.png", PNG, "image/png")})
    assert r.status_code == 422


def test_media(client, auth, monkeypatch):
    from app.services import media

    data = {"query": {"pages": {
        "2": {"index": 2, "imageinfo": [{"thumburl": "https://x/b.jpg", "descriptionurl": "https://c/B",
                                         "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}}}]},
        "1": {"index": 1, "imageinfo": [{"thumburl": "https://x/a.jpg", "descriptionurl": "https://c/A",
                                         "extmetadata": {"Artist": {"value": '<a href="u">Sonett72</a> at <a>Wikipedia</a>'},
                                                         "LicenseShortName": {"value": "Public domain"}}}]},
        "0": {"index": 0, "imageinfo": [{"thumburl": "https://x/nolicence.jpg", "extmetadata": {}}]},
    }}}
    photo = media.parse_commons(data)  # most relevant result with a licence, author as plain text
    assert (photo.thumb_url, photo.author, photo.license) == ("https://x/a.jpg", "Sonett72 at Wikipedia", "Public domain")
    assert media.parse_commons({}) is None

    async def fake_photo(part):
        return photo if part == "ignition coil" else None

    monkeypatch.setattr(media, "part_photo", fake_photo)
    assert client.get("/api/media/part-photo", params={"q": "ignition coil"}).status_code == 401
    r = client.get("/api/media/part-photo", params={"q": "ignition coil"}, headers=auth)
    assert r.status_code == 200 and r.json()["license"] == "Public domain"
    assert client.get("/api/media/part-photo", params={"q": "flux capacitor"}, headers=auth).status_code == 404

    # No YOUTUBE_API_KEY in tests: null, the app falls back to a YouTube search link
    assert client.get("/api/media/video", params={"q": "Corolla spark plugs"}, headers=auth).json() is None


def test_prompt_asks_for_media_tag(client, auth):
    from app.models import Vehicle
    from app.services.prompts import build_system_prompt

    prompt = build_system_prompt(Vehicle(make="Toyota", model="Corolla", year=2016))
    assert '<!-- mikaniki-media {"parts": ["ignition coil", "spark plug"]' in prompt


def test_parts_catalog(client, auth, monkeypatch):
    """Categories -> part list by VIN; the EPC code is decoded once and kept on the car."""
    from app.services import vin17

    calls = []

    async def fake_call(path, params):
        calls.append((path, params.get("action")))
        if path == "/":
            return {"epc": "toyota", "epc_id": "7"}
        if params["action"] == "cata1":
            return {"catalist": [{"cata_level": 1, "is_last": 0, "cata_code": "09", "name_en": "1 Tools",
                                  "name_zh": "工具", "illustration_img_address": "", "Is_fit_for_this_vin": 1}]}
        if params["action"] == "cata2":
            assert params["cata1_code"] == "09"
            return {"catalist": [{"cata_level": 2, "is_last": 1, "cata_code": "0901_090562C-0001",
                                  "name_en": "Jack", "illustration_img_address": "090562C.png",
                                  "is_fit_for_this_vin": 0}]}
        assert params == {"action": "part", "vin": "JTDBR32E720123456",
                          "last_cata_code": "0901_090562C-0001", "last_cata_code_level": "2"}
        return {"imgaddress": "090562C.png",
                "partlist": [{"callout": "09114", "partnumber_original": "09114-0G010", "partnumber": "091140G010",
                              "name_en": "EXTENSION, JACK HANDLE", "qty": "01", "is_fit_for_this_vin": 1,
                              "illustration_img_address": "090562C.png"},
                             {"partnumber": "9155180625", "name_zh": "标准件"}],
                "all_img_hotspots": [{"img_hotspots": {"img_name": "090562C.png", "img_width": 200, "img_height": 400,
                                                       "hotspots": [{"callout": "09114", "topleft_x": 50, "topleft_y": 100},
                                                                    {"callout": "09114", "topleft_x": 50, "topleft_y": 100},
                                                                    {"callout": "", "topleft_x": 1, "topleft_y": 1}]}}]}

    monkeypatch.setattr(vin17, "enabled", lambda: True)
    monkeypatch.setattr(vin17, "call", fake_call)
    vin17._cache.clear()

    no_vin = client.post("/api/vehicles", headers=auth, json={"make": "Toyota", "model": "Corolla", "year": 2002}).json()
    assert client.get(f"/api/vehicles/{no_vin['id']}/parts/categories", headers=auth).status_code == 409

    car = client.post("/api/vehicles", headers=auth, json={
        "make": "Toyota", "model": "Corolla", "year": 2002, "vin": "JTDBR32E720123456", "source": "vin"}).json()
    base = f"/api/vehicles/{car['id']}/parts"
    top = client.get(f"{base}/categories", headers=auth).json()
    assert top == [{"code": "09", "name": "Tools", "name_zh": "工具", "remark": None, "level": 1,
                    "is_last": False, "fits": True, "image": None}]
    sub = client.get(f"{base}/categories", headers=auth, params={"parent": "09", "parent_level": 1}).json()
    assert sub[0]["is_last"] and not sub[0]["fits"]
    assert sub[0]["image"] == "/api/parts-img/toyota/090562C.png"
    parts = client.get(base, headers=auth, params={"code": "0901_090562C-0001", "level": 2}).json()
    assert parts["image"] == "/api/parts-img/toyota/090562C.png"
    p = parts["parts"][0]
    assert (p["number"], p["name"], p["callout"], p["qty"], p["fits"]) == (
        "091140G010", "Extension, Jack Handle", "09114", "1", True)
    assert parts["parts"][1]["name"] == "Standard hardware (bolt, nut, clip)"
    assert parts["hotspots"] == [{"callout": "09114", "x": 25.0, "y": 25.0}]

    async def fake_image(epc, name):
        return (PNG, "image/png") if (epc, name) == ("toyota", "090562C.png") else None

    monkeypatch.setattr(vin17, "fetch_image", fake_image)
    img = client.get("/api/parts-img/toyota/090562C.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert client.get("/api/parts-img/toyota/other.png").status_code == 404

    from app.db import SessionLocal
    from app.models import Vehicle
    with SessionLocal() as db:
        assert db.get(Vehicle, car["id"]).vin_data["epc"] == "toyota"
    assert calls.count(("/", None)) == 1  # VIN decoded once

    assert client.get(f"{base}/categories", headers=auth, params={"parent": "09"}).status_code == 422
    assert client.get(f"{base}/categories").status_code == 401
    monkeypatch.setattr(vin17, "enabled", lambda: False)
    assert client.get(f"{base}/categories", headers=auth).status_code == 503


def test_mock_opens_parts_catalog(client, auth):
    car = client.post("/api/vehicles", headers=auth, json={"make": "Kia", "model": "Rio", "year": 2015}).json()
    conv = client.post(f"/api/vehicles/{car['id']}/conversations", headers=auth).json()
    r = client.post(f"/api/conversations/{conv['id']}/messages", headers=auth, data={"text": "show me the parts"})
    assert '"catalog": true' in r.json()["assistant_message"]["content"]


def test_find_part_diagram(monkeypatch):
    """Part name -> best catalog section: the part itself beats accessories and look-alikes."""
    import asyncio

    from app.services import vin17

    async def fake_categories(epc, vin, parent=None, parent_level=0):
        if parent is None:
            return [{"code": "4", "name": "Chassis", "level": 1, "is_last": False, "fits": True}]
        return [{"code": "pedal", "name": "Brake Pedal & Bracket", "level": 2, "is_last": True, "fits": True},
                {"code": "front", "name": "Front Disc Brake Caliper", "level": 2, "is_last": True, "fits": True},
                {"code": "chain", "name": "Timing Gear Cover", "level": 2, "is_last": True, "fits": True}]

    async def fake_parts(epc, vin, code, level):
        names = {"pedal": [("47121", "Pad, Brake Pedal")],
                 "front": [("04465", "Pad Kit, Disc Brake, Front"), ("47750", "Caliper Assy, Front")],
                 "chain": [("11310", "Cover Sub-Assy, Timing Chain")]}[code]
        return {"image": f"/api/parts-img/toyota/{code}.png",
                "hotspots": [{"callout": n, "x": 10, "y": 20} for n, _ in names],
                "parts": [{"callout": n, "number": n + "000", "name": name, "fits": True} for n, name in names]}

    monkeypatch.setattr(vin17, "categories", fake_categories)
    monkeypatch.setattr(vin17, "parts", fake_parts)
    r = asyncio.run(vin17.find_part("toyota", "VIN", "brake pads"))
    assert r["section"]["code"] == "front" and [p["number"] for p in r["parts"]] == ["04465000"]
    assert r["hotspots"] == [{"callout": "04465", "x": 10, "y": 20}]
    assert asyncio.run(vin17.find_part("toyota", "VIN", "timing chain")) is None  # only its cover
    assert asyncio.run(vin17.find_part("toyota", "VIN", "wheel bearing")) is None


def test_find_part_by_chinese_name(monkeypatch):
    """17VIN names parts in Chinese only: the LLM's terms are matched to the car's part-name list."""
    import asyncio

    from app.services import vin17

    names = ["曲轴位置传感器", "曲轴", "制动总泵分总成", "后桥右轮毂和轴承总成", "正时链条盖分总成", "螺栓（用于曲轴皮带轮组件）"]
    assert vin17.best_name(names, ["曲轴位置传感器"]) == "曲轴位置传感器"           # exact
    assert vin17.best_name(names, ["轮毂轴承"]) == "后桥右轮毂和轴承总成"            # close enough
    assert vin17.best_name(names, ["制动分泵"]) is None                            # wheel cylinder != master cylinder
    assert vin17.best_name(names, ["曲轴皮带轮"]) is None                          # only a bolt "for" it

    async def fake_names(epc, vin):
        return names

    async def fake_search(epc, vin, name):
        rows = {"曲轴位置传感器": ("1105_118448B-0002", "1>1105_0002>CYLINDER BLOCK", "9091905070", "11401G"),
                "正时链条盖分总成": ("1106_11D487A-0001", "1>1106_0001>TIMING GEAR COVER", "113100T042", "11302")}[name]
        return [{"cata_code": rows[0], "cata_level": 0, "cata_name_en": rows[1], "partnumber": rows[2],
                 "callout": rows[3], "is_fit_for_this_vin": 1}]

    async def fake_parts(epc, vin, code, level):
        assert level == 2  # depth of "1>1105_0002>CYLINDER BLOCK"
        part = {"1105_118448B-0002": ("9091905070", "Sensor, Crank Position", "11401G"),
                "1106_11D487A-0001": ("113100T042", "Cover Sub-Assy, Timing Chain", "11302")}[code]
        return {"image": "/api/parts-img/toyota/x.png", "hotspots": [{"callout": part[2], "x": 1, "y": 2}],
                "parts": [{"number": part[0], "name": part[1], "callout": part[2], "fits": True}]}

    monkeypatch.setattr(vin17, "all_part_names", fake_names)
    monkeypatch.setattr(vin17, "search_name", fake_search)
    monkeypatch.setattr(vin17, "parts", fake_parts)
    r = asyncio.run(vin17.find_part_by_name("toyota", "VIN", "crankshaft position sensor", ["曲轴位置传感器"]))
    assert r["section"] == {"code": "1105_118448B-0002", "name": "Cylinder Block", "level": 2}
    assert [p["number"] for p in r["parts"]] == ["9091905070"] and len(r["hotspots"]) == 1
    assert asyncio.run(vin17.find_part_by_name("toyota", "VIN", "timing chain", ["正时链条"])) is None
