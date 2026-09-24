# Note Printer

Een zelfstandige Umbrel-app om notities op een via USB aangesloten DYMO LabelWriter 400 of 450 te printen. De app gebruikt DYMO 99014-labels (54 × 101 mm).

## Wat kan de app?

- Titel, notitie en regelafbrekingen invoeren vanaf telefoon of computer.
- Een benadering op het scherm en een exacte PDF als afdrukvoorbeeld tonen.
- Datum en tijd toevoegen en 1–10 exemplaren kiezen.
- De LabelWriter automatisch herkennen en de CUPS-printer bij het afdrukken instellen.
- Te lange notities tegenhouden voordat een afdruktaak wordt verzonden.
- Negen ingebouwde sjablonen met eigen labelindeling: boodschappen, taken, herinnering, berichtje, afspraak, pakket, waarschuwing, instructies en contact.
- Eigen sjablonen maken en bewaren met koptekst, lettergrootte, afvinklijst, inhoud en gekozen indeling.
- Notities bewaren, opnieuw openen en wijzigen. Een afdrukgeschiedenis met opnieuw printen en verwijderen.
- Een printerpagina met de CUPS-status, wachtrij en mogelijkheid om een afdruktaak te annuleren.
- Velden Aan, Van en afspraakdatum of tijd, plus een pictogram of zwart-witfoto op het label.
- Een Siri Opdrachten-link om op je iPhone tekst vooraf in te vullen en de afdruk in de app te bevestigen.
- Optionele afvinkvakjes vóór elke ingevulde regel.
- Lange notities optioneel over maximaal 10 genummerde labels verdelen.
- Een QR-code van maximaal 300 tekens met een link of andere tekst op het laatste label.

## Installeren in Umbrel

1. Open in de Umbrel App Store het menu **Community App Stores**.
2. Voeg `https://github.com/TheRoyalCaptain/Note-Printer` toe.
3. Open **Note Printer** in die store en installeer de app.
4. Sluit de DYMO via USB op dezelfde Umbrel-server aan en plaats een rol 99014-labels.

De GitHub Actions-workflow bouwt de image voor AMD64 en ARM64 en publiceert deze in GHCR. Wacht op een geslaagde workflow en een openbaar pakket voordat je de app installeert. De Umbrel-proxy beschermt de app met zijn toegangsscherm; de app heeft geen extra eigen account.

## Gebruik

Open Note Printer vanuit Umbrel, kies een sjabloon en druk op **Toepassen**. Dat vult voorbeeldtekst in én zet de bijpassende labelindeling aan. Boodschappen hebben een donkere kop en afvinkregels, taken en instructies een genummerde lijst, herinneringen en waarschuwingen een accentlijn, en berichten, pakketten en contacten een omlijnd tekstvak. Je kunt de inhoud aanpassen zonder de indeling te verliezen. Kies **Vrije notitie → Toepassen** voor een gewone notitie met de bestaande tekst.

Onder **Eigen opmaak en sjabloon bewaren** kun je de indeling, een eigen koptekst en een lettergrootte kiezen. De opgeslagen sjablonen verschijnen in de keuzelijst. **Notitie bewaren** slaat de huidige inhoud op; onder **Opgeslagen** kun je haar weer openen of verwijderen. De informatie blijft in de appgegevens op Umbrel staan. De afdrukgeschiedenis onthoudt zowel verzonden als mislukte opdrachten, zodat je ze opnieuw kunt proberen of verwijderen. Een verzonden opdracht is nog geen bevestiging dat het label fysiek is geprint.

Zet desgewenst afvinkvakjes of meerdere labels aan, vul Aan/Van en een afspraakmoment in, kies een pictogram of foto en voeg QR-inhoud toe. Een foto wordt in de browser verkleind en in zwart-wit op het label gezet. Het scherm vermeldt het aantal labels per exemplaar. Bekijk de volledige PDF voordat je op **Print notitie** drukt. Op het scherm **Printer** kun je de aansluiting en wachtrij nakijken. De printer moet zijn aangesloten op het apparaat waarop Umbrel draait. De DYMO 5-serie wordt niet ondersteund. Printen moet op jouw hardware worden gecontroleerd.

Voor een iPhone-snelkoppeling: kopieer op de pagina **Printer** de URL, laat Siri Opdrachten de gewenste tekst via **URL encodeer** omzetten en plak die achter `?text=` in de URL. Laat **Open URL's** die complete URL openen. De app vult de notitie in; je bekijkt het label en drukt zelf op **Print notitie**. De Umbrel-login blijft van toepassing.

## Lokale ontwikkeling

`docker compose up --build -d` en open `http://localhost:8080`. Houd de lokale ontwikkelpoort op een vertrouwd netwerk: buiten Umbrel is geen login aanwezig.

Tests uitvoeren: `python -m unittest discover -s tests`.

Opgeslagen notities, sjablonen en afdrukgeschiedenis staan in SQLite onder `/data` (bij Umbrel: de persistente appgegevens). Het PDF-voorbeeld blijft in het browsergeheugen; de printopdracht gebruikt een tijdelijk bestand dat na het versturen wordt verwijderd. Verwijder de appgegevens alleen als je ook de bewaarde inhoud wilt verwijderen.
