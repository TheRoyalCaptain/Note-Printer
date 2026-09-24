# Note Printer

Een zelfstandige Umbrel-app om notities op een via USB aangesloten DYMO LabelWriter 400 of 450 te printen. De app gebruikt DYMO 99014-labels (54 × 101 mm).

## Wat kan de app?

- Titel, notitie en regelafbrekingen invoeren vanaf telefoon of computer.
- Een benadering op het scherm en een exacte PDF als afdrukvoorbeeld tonen.
- Datum en tijd toevoegen en 1–10 exemplaren kiezen.
- De LabelWriter automatisch herkennen en de CUPS-printer bij het afdrukken instellen.
- Te lange notities tegenhouden voordat een afdruktaak wordt verzonden.
- Sjablonen voor boodschappen, taken, herinneringen en berichtjes.
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

Open Note Printer vanuit Umbrel, kies eventueel een sjabloon en druk op **Toepassen**. Pas de tekst aan, zet desgewenst afvinkvakjes of meerdere labels aan, en voeg QR-inhoud toe. Het scherm vermeldt het aantal labels per exemplaar. Bekijk de volledige PDF voordat je op **Print notitie** drukt. De printer moet zijn aangesloten op het apparaat waarop Umbrel draait. De DYMO 5-serie wordt niet ondersteund. Printen moet op jouw hardware worden gecontroleerd.

## Lokale ontwikkeling

`docker compose up --build -d` en open `http://localhost:8080`. Houd de lokale ontwikkelpoort op een vertrouwd netwerk: buiten Umbrel is geen login aanwezig.

Tests uitvoeren: `python -m unittest discover -s tests`.

Notities worden niet opgeslagen. Het PDF-voorbeeld blijft in het browsergeheugen; de printopdracht gebruikt alleen een tijdelijk bestand dat na het versturen wordt verwijderd.
