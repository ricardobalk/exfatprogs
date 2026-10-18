# ADR 0001: allocatie- en writebackinvarianten

Status: lokaal geïmplementeerd; niet door upstream geaccepteerd.

Een virtuele knoop vertegenwoordigt precies één niet-lege allocatie. Root komt
éénmaal voor; een lege stream of lege vendorallocatie consumeert geen knoop.
De lees- en schrijfpassen gebruiken dezelfde directoryvolgorde. Een afwijkende
verplaatsingsvolgorde mag de indexering niet herschikken.

Iedere fysieke cluster heeft vóór verplaatsing exact één verklaarde eigenaar.
Preflight controleert bereik, lengte, cycli, crosslinks, actieve entries en
bitmap. Onbekende allocaties en slechte clusters leiden in deze eerste scope
tot afwijzing; ze worden nooit als vrije bestemming behandeld. NoFatChain
maakt de corresponderende FAT-velden ongeldig: stale FAT-inhoud bij zulke
bestanden wordt niet als werkelijk eigendom of als bad-clusterregistratie gelezen.

De worker verwerkt bitmap/upcase eerst tot contiguous ketens, ook bij een
cancellationverzoek. Daarna mag hij tussen gewone swaps stoppen. Metadatawriteback
berekent NoFatChain uit de werkelijke keten. De root gebruikt altijd FAT.
De nieuwe FAT moet beschikbaar zijn voordat de iterator nieuwe directoryketens
volgt. Iedere entrychecksum wordt na de laatste mutatie berekend. Alleen het
vierbyte-rootveld van beide bootsectors wordt gewijzigd; checksumsectoren worden
met de logische sectorgrootte vernieuwd.

Deze volgorde levert geen bescherming tegen een crash tussen twee writes.
Daarvoor geldt ADR 0002. Bij een workerfout wordt geen geldige tussentoestand
geclaimd; de interface houdt het journal actief. Succes vereist onafhankelijke
inhouds-/metadatavergelijking en nul resterende discontinuïteiten.

Afgewezen alternatief: een indexgrens (`interrupt_point`) gebruiken als bewijs
van contiguïteit. Swaps kunnen toekomstige ketens wijzigen; een verwerkingsgrens
zegt daarom niets over hun actuele fysieke links.
