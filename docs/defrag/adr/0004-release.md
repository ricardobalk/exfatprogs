# ADR 0004: vrijgavegates en status

Status: lokaal vrijgavebeleid; geen upstreamacceptatie.

Drie onderscheiden statussen:

1. **Functioneel hersteld binnen de beschreven scope:** oorspronkelijke
   corruptieregressies falen op de vastgepinde baseline en slagen na herstel;
   on-disk inhoud, metadata, allocaties en fragmentatie zijn onafhankelijk getest.
2. **Experimenteel bruikbaar op kleine offline Linux-images:** strikte
   ondersteuningsmatrix, read-only analyse, undo/commit/herstel, signalen en
   kopieerpublicatie zijn geïmplementeerd. De huidige ingang heeft deze status
   zodra de gedocumenteerde lokale tests slagen.
3. **Gekwalificeerd voor rechtstreeks gebruik op volumes:** niet toegekend.
   Blockdevices zijn niet geïmplementeerd; de normale build/installatie blijft uit.

Groene lokale tests zijn noodzakelijk maar niet voldoende om de derde status
te claimen. Resterende gates: blockdevice-identiteit en exclusiviteit,
herstel op representatieve opslag met werkelijk stroomverlies en aantoonbare
flushgaranties, grote volumes/64-bit grenzen op echte layouts, bad-clusterlayouts,
bredere vendor- en systeemallocaties, overige platformen en onafhankelijke review.
TexFAT wordt expliciet niet ondersteund. De bestaande 2-TB upstream-fsckfixture
kwalificeert de nieuwe defrag-engine niet voor een volume van 2 TB.

Een NOT_RUN is geen PASS. De volledige kwalificatierunner meldt een ontbrekende
driverproef zichtbaar; iedere overeenkomstige claim blijft dan geblokkeerd.
Exacte gemeten aantallen staan in qualification.md, met verwijzingen naar
machineleesbare caserecords. De historische contextcijfers tellen niet mee.

Een gewijzigde supportmatrix, herstelvolgorde of writer vereist nieuwe relevante
tests en herbeoordeling van deze gates. Het in normale builds zetten van alleen
de herstelde C-worker zou het herstelprotocol omzeilen en is niet toegestaan.
