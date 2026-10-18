# Traceability en grenzen

Een PASS geldt voor de beschreven experimentele imagescope. De laatste kolom
maakt ontbrekend bewijs of afwijkingen van de ruimere opdracht zichtbaar.

| Requirement | Code | Proef | Werkelijk bewijs / beperking |
| --- | --- | --- | --- |
| F01 inhoud, paden, metadata, VDL | defrag.c writeback; layout.py equivalent | run.py, mounted.py, metadata.py | model.json, driver.json, metadata.json; raw allocatievelden daarnaast inhoudelijk gevalideerd |
| F02 meetbare defragmentatie | layout.py report; defrag.c swaps | onafhankelijke Image.inspect, tweede no-op | model-cases.jsonl; discontinuïteiten/extents per allocatie, geen gaps tussen bestanden |
| F03 volledige preflight | layout.py; BFS_read_file_tree ownership | negative.py, volle fixtures | negative.json, matrix.json, model-cases.jsonl; bad-clustervolumes geweigerd, niet gedefragmenteerd; gefragmenteerde invoersystemen en algemene vendors niet ondersteund |
| F04 read-only/interface | Image/check_loops/flock; CLI | dry-runhash per modelseed; negative.py; mounted.py | model-cases.jsonl, negative.json, driver.json; locks advisory, namespaces beperkt zichtbaar |
| S01 cancellation | sig_atomic_t in C; Python handler registreert | iedere kleine workerwrite; host/recoverygrenzen | fault-cases.jsonl; status 130/143 en exacte rollback; commitbatch kan geldige nieuwe staat behouden |
| S02 echt herstelprotocol | image_defrag.py Journal | faults.py, persistence.py, transaction_regressions.py | faults.json, persistence.json, transactions.json; bounded regulier-imagehost, geen blockdevicekwalificatie of werkelijk power-cut hardwarebewijs |
| S03 kopieerworkflow | defrag_image.py | publication.py | publication.json; bronhash, corruptie, kill, output-race/no-replace, zichtbaarheid na directoryflushfout |
| TEST01 oude defecten | pinned build.py baseline | regressions.py, negen gerichte cases | baseline.json versus regressions.json; foutinjectie in raw worker belooft alleen foutpropagatie, herstel wordt apart getest |
| TEST02 1.000 × 5.000 | image.py model; parallel.py partitions | native + ASan/UBSan, elk 1.000 seeds en twee extra capacitycases | model.json, sanitizer-model.json; iteraties/effectieve mutaties/drivercalls afzonderlijk; 288 factoriële layouts per build in matrix.json; encoded grote waarden in negative.json, geen grote-volume-relocatieclaim |
| TEST03 onafhankelijke reader en fsck | image.py, fsck.exfat | alle model- en driverimages vóór/na | caserecords met fsckstatus, volledige semantische vergelijking; reader importeert layout.py niet |
| TEST04 10 × 5.000 driver | mounted.py private mountnamespace | Linux-driver, unmount, defrag, remount | driver.json; alleen eigen tijdelijke images en losetup-devices; expliciete workload-os-calls geteld |
| TEST05 short/EINTR/zero/EIO/ENOSPC/flush/signalen/kill | fault.c, Faults | faults.py, persistence.py, publication.py | alleen werkelijk geraakte posities tellen; kleine fixturegrenzen exhaustief, grotere layouts model-/driverproeven; geen exhaustieve fouten op alle grote fixtures |
| TEST06 sanitizers en upstream | expliciete sanitizerbuild | full model; fault-/herstel-/publicatie-/negatieve suites en upstream | sanitizer-*.json; ASan én UBSan met lekdetectie; geen uitgeschakelde check als PASS |
| Reproduceerbaarheid | build.py, qualify.py, minimize.py | smoketest; afzonderlijke volledige onderdelen | environment.json, commands.json, bron-/binaryhashes; prefixverkleiner geïmplementeerd, geen minimisatieclaim |
| Normale vrijgave | Makefile.am/configure.ac ongewijzigd | build/source-inspectie | BLOCKED voor rechtstreekse gebruikersvolumes; ADR 0004 |

`image.py` bevat zowel de fixturegenerator als de onafhankelijke reader. Dat
maakt de serializer niet onafhankelijk van zijn eigen opmaakhelpers, maar de
verwachte bestandsbytes komen uit een extern model en de reader is volledig
onafhankelijk van de te testen C-engine en productiepreflight. De driverproef
voegt een serializer toe die werkelijk onafhankelijk is: de Linux-driver.
