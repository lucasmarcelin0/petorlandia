import json
from bs4 import BeautifulSoup


def test_public_home_brand_seo_and_structured_data(client):
    """A home pública deve conter as grafias de marca no title, meta tags e Schema.org."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    soup = BeautifulSoup(html, "html.parser")

    # 1. Title e Meta Tags
    title = soup.find("title")
    assert title is not None
    assert "PetOrlândia (Pet Orlândia)" in title.text

    meta_desc = soup.find("meta", attrs={"name": "description"})
    assert meta_desc is not None
    assert "PetOrlândia (Pet Orlândia)" in meta_desc["content"]

    meta_kw = soup.find("meta", attrs={"name": "keywords"})
    assert meta_kw is not None
    kw_content = meta_kw["content"].lower()
    assert "petorlandia" in kw_content
    assert "pet orlandia" in kw_content
    assert "pet orlândia" in kw_content

    # 2. Textos visíveis no Hero
    hero_kicker = soup.select_one(".unified-kicker")
    assert hero_kicker is not None
    assert "PetOrlândia (Pet Orlândia)" in hero_kicker.text

    # 3. Dados estruturados JSON-LD
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    assert len(scripts) >= 1

    org_found = False
    software_found = False
    for script in scripts:
        try:
            data = json.loads(script.string)
        except Exception:
            continue

        graph = data.get("@graph", [data])
        for item in graph:
            if item.get("@type") == "Organization":
                org_found = True
                assert item.get("name") == "PetOrlândia"
                alternates = item.get("alternateName", [])
                assert "Pet Orlândia" in alternates
                assert "Petorlandia" in alternates
                assert "Pet Orlandia" in alternates

            if item.get("@type") == "SoftwareApplication":
                software_found = True
                assert item.get("name") == "PetOrlândia"
                alternates = item.get("alternateName", [])
                assert "Pet Orlândia" in alternates
                assert "Petorlandia" in alternates
                assert "Pet Orlandia" in alternates

    assert org_found, "Schema Organization não encontrado na home pública"
    assert software_found, "Schema SoftwareApplication não encontrado na home pública"


def test_sobre_page_has_alternate_name(client):
    """A página sobre deve incluir alternateName para a organização."""
    response = client.get("/sobre")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    soup = BeautifulSoup(html, "html.parser")

    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    assert len(scripts) >= 1

    found = False
    for script in scripts:
        try:
            data = json.loads(script.string)
        except Exception:
            continue
        graph = data.get("@graph", [data])
        for item in graph:
            works_for = item.get("worksFor")
            if works_for and works_for.get("@type") == "Organization":
                alternates = works_for.get("alternateName", [])
                if "Pet Orlândia" in alternates and "Petorlandia" in alternates:
                    found = True
    assert found, "Organization com alternateName não encontrada em /sobre"


def test_apex_domain_redirects_to_www_https(app):
    """Requisições para petorlandia.com.br devem ser redirecionadas via 301 para https://www.petorlandia.com.br."""
    with app.test_request_context(
        "/",
        base_url="http://petorlandia.com.br",
        headers={"Host": "petorlandia.com.br"},
    ):
        app.config["TESTING"] = False
        try:
            from request_hooks import _redirect_insecure_request
            resp = _redirect_insecure_request()
            assert resp is not None
            assert resp.status_code == 301
            assert resp.headers["Location"] == "https://www.petorlandia.com.br/"
        finally:
            app.config["TESTING"] = True
