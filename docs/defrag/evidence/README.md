# Eigen bewijs, 18 oktober 2026

Deze map bevat uitsluitend eigen eindresultaten. De historische contextbestanden
zijn niet als PASS overgenomen. [qualification.md](../qualification.md) legt de
cijfers, scope en vrijgavestatus uit; [requirements.md](../requirements.md) koppelt
de eisen aan code, tests en bewijs.

- `model*.json*` en `sanitizer-model*.json*`: twee afzonderlijke uitvoeringen van
  1.000 × 5.000 modeliteraties plus twee capacitycases. Geen drivercallclaim.
- `matrix*.json*`: 288 factoriële layouts per build, apart van de 1.000 seeds.
- `driver.json`: werkelijk Linux-exFAT-drivergebruik, tien seeds, inclusief
  unmount/remount, inhoud/metadata en afwijzing van attached loopimages/devices.
- `baseline.json`, `regressions.json`, `sanitizer-regressions.json`: negen
  doelgerichte oude fouten versus herstelde uitkomsten. Baseline-PASS betekent
  juist dat het defect is aangetoond.
- `faults*.json*`, `fault-*-boundaries.json`: geplande én geraakte injecties,
  echte writerposities, herstel en exitstatussen. Vijf onbetrouwbare-journalcases
  zijn geen fault-injecties en worden niet bij de 646 hits opgeteld.
- `persistence*.json*`: expliciet verlies-/herordenings-/torn-writemodel, apart
  van SIGKILL. `publication.json` bevat ook zichtbaarheid na de link en fouten.
- `negative.json`, `transactions.json`, `metadata.json` en hun sanitizertegenhangers:
  gerichte grens- en behoudsproeven, inclusief niet-blokkerende FIFO-afwijzing.
- `upstream.json`, `sanitizer-upstream.json`, `autotools.log`, `internal-tests.log`:
  bestaande fixtures en interne buildtests. Grote sparse fsckfixtures zijn geen
  bewijs van grote-volume-defrag.
- `clean-apply.json`: volledige commitreeks schoon toegepast op de uitgangsbasis,
  gevolgd door build/smoke en upstreamsuite in die aparte checkout.
- `environment.json`, `build.json`, `sanitizer-build.json`, `baseline-build.json`:
  compiler/platform/dependencies en bron-/binaryhashes. Modelrapporten bewaren
  ook de bronhashes van hun startmoment; nieuwe testhulpcode staat in environment.
- `additional.json`, `sanitizer-additional.json`, `commands.json`: daadwerkelijk
  gebruikte commando's. De full-orchestrator is beschikbaar; de uitgebreide
  bewijsset is per onderdeel uitgevoerd. `smoke.json` is wel een uitgevoerde
  volledige korte orchestratorrun.

De files `*-cases.jsonl` bevatten één object per uitgevoerde testcase. Succesvolle
images zijn verwijderd; falende experimenten en grote lokale logs staan in de
geïgnoreerde `build-defrag-tests*`-mappen. De eindbewijsset bevat geen niet-uitgevoerde
proef als PASS. De prefixverkleiner is beschikbaar maar wordt niet als uitgevoerde
minimalisatie geteld.

`manifest.json` bevat SHA-256 per bestand in deze map, behalve zichzelf. Controle:

```sh
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path('docs/defrag/evidence')
for name, expected in json.loads((p/'manifest.json').read_text()).items():
    assert hashlib.sha256((p/name).read_bytes()).hexdigest() == expected, name
print('artifact hashes match')
PY
```
