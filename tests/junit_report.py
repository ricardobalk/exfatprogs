#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Convert qualification JSON evidence to descriptive JUnit XML."""
import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


INTENTS = {
    'missing': {
        'what': 'Qualification report availability',
        'why': 'Every CI test job must leave machine-readable evidence, including after a test failure.',
        'where': 'The selected qualification output directory.',
        'impact': 'Without a report, GitHub could hide which safety check stopped or never ran.',
    },
    'orchestration': {
        'what': 'Qualification campaign steps',
        'why': 'Every required build and test group must run before the campaign can support a qualification claim.',
        'where': 'The top-level qualification runner.',
        'impact': 'A skipped or failed step leaves part of the feature unqualified.',
    },
    'resize-library': {
        'what': 'Resize library unit and integration contracts',
        'why': 'Geometry, allocation, directory, transaction, grow, and shrink primitives must agree before an image is changed.',
        'where': 'The C resize library on disposable in-memory and image fixtures.',
        'impact': 'A mismatch can corrupt allocation metadata or move file data to the wrong cluster.',
    },
    'resize-host': {
        'what': 'Resize host interface and fail-closed validation',
        'why': 'Invalid sizes, corrupt images, and unsafe transaction states must be rejected before writes start.',
        'where': 'The Python image host and command-line boundary.',
        'impact': 'An unsafe request could otherwise create a journal or modify an image that cannot be recovered.',
    },
    'resize-model': {
        'what': 'Seeded grow and shrink image preservation',
        'why': 'Allocated clusters may move, but file bytes, metadata, geometry, and newly added capacity must remain usable.',
        'where': 'Deterministic exFAT images with varied sector, cluster, FAT, and tail layouts.',
        'impact': 'For example, a successful-looking shrink could silently lose a file stored near the old end of the volume.',
    },
    'resize-faults': {
        'what': 'Resize interruption and storage-fault recovery',
        'why': 'Each reached write or durability boundary must recover to one complete old or new filesystem state.',
        'where': 'Disposable images with injected kill, I/O, no-space, short-transfer, EINTR, and cancellation faults.',
        'impact': 'A partial transition could otherwise leave a volume that neither the resizer nor fsck can recover.',
    },
    'resize-large-faults': {
        'what': 'Large-image sampled fault recovery',
        'why': 'Fault behavior must also hold when relocation spans many clusters and an 8 MiB modeled file.',
        'where': '128 MiB images resized to 80 MiB and 192 MiB at selected persistence boundaries.',
        'impact': 'A bug visible only across larger copy ranges could corrupt real multi-cluster files.',
    },
    'resize-fsck': {
        'what': 'Existing fsck regression fixtures',
        'why': 'Resize-related checker changes must preserve detection, repair, and clean reread of known corrupt images.',
        'where': 'The repository fsck fixture corpus, with sanitizer coverage where selected.',
        'impact': 'A checker regression could accept corruption or make a damaged image worse during repair.',
    },
    'resize-counterexample': {
        'what': 'Fragmented upcase-table checker counterexample',
        'why': 'A legal fragmented system stream must be accepted, and a repaired stream must receive a valid FAT chain.',
        'where': 'The pinned pre-change checker and the current checker on the same synthetic image.',
        'impact': 'The old behavior rejects valid media and can create an unreadable repaired system stream.',
    },
    'resize-container': {
        'what': 'Whole-disk and hybrid-container rejection',
        'why': 'The image-only resizer must distinguish a plain exFAT volume from MBR or GPT containers before writing.',
        'where': 'Plain, MBR-hybrid, and GPT image layouts.',
        'impact': 'Treating a disk container as a volume could overwrite its partition metadata.',
    },
    'resize-nofat': {
        'what': 'Inactive FAT entry handling',
        'why': 'NoFatChain streams use contiguous allocation, so inactive FAT garbage must not be followed as a live chain.',
        'where': 'Four real image geometries with free, bad-marker, and out-of-range inactive FAT values.',
        'impact': 'A validator could reject a valid image or report unrelated clusters as file data.',
    },
    'resize-signals': {
        'what': 'Real Unix signal cancellation',
        'why': 'SIGINT and SIGTERM must stop normal work safely but must not interrupt mandatory rollback.',
        'where': 'Live resize and recovery processes at observed journal and source-write boundaries.',
        'impact': 'Stopping recovery halfway could leave mixed old and new filesystem bytes.',
    },
    'resize-compound': {
        'what': 'Combined cancellation and commit-flush failure',
        'why': 'An I/O error after commit-marker rename must take priority over cancellation and preserve the committed state for recovery.',
        'where': 'The recorded vulnerable host and current host under the same compound fault.',
        'impact': 'Undoing after a durable commit can mix states and make both normal use and recovery fail.',
    },
    'resize-driver': {
        'what': 'Linux exFAT driver interoperability',
        'why': 'Files created through the kernel driver must survive offline resize, remount, comparison, and added-capacity writes.',
        'where': 'Private disposable loop images mounted by the Linux exFAT driver.',
        'impact': 'A structurally valid image could still be unusable by the operating system that mounts it.',
    },
    'defrag-regressions': {
        'what': 'Directed defrag regressions',
        'why': 'Each historical defect must reproduce on the pinned baseline and pass with the repaired worker.',
        'where': 'Focused fragmented image fixtures and controlled worker faults.',
        'impact': 'A previously demonstrated corruption, status, or durability bug could return unnoticed.',
    },
    'defrag-model': {
        'what': 'Seeded defrag content and metadata preservation',
        'why': 'Defragmentation may change physical cluster placement only; logical files and metadata must remain identical.',
        'where': 'Rootless deterministic images across sector, cluster, vendor, occupancy, and tail layouts.',
        'impact': 'For example, reducing extents could silently alter a file or directory entry.',
    },
    'defrag-faults': {
        'what': 'Defrag transaction fault recovery',
        'why': 'Every reached host and worker boundary must recover to exact old bytes or a complete defragmented state.',
        'where': 'Disposable images with process, I/O, no-space, signal, and repeated-recovery faults.',
        'impact': 'A crash during relocation could otherwise leave valid-looking metadata pointing at incomplete data.',
    },
    'defrag-persistence': {
        'what': 'Defrag persistence replay model',
        'why': 'Lost, reordered, and torn volatile worker writes before commit must be reversible from the durable journal.',
        'where': 'Recorded worker writes replayed as prefixes, subsets, reverse orders, and half writes.',
        'impact': 'A storage interruption could otherwise defeat rollback even when the journal itself is durable.',
    },
    'defrag-publication': {
        'what': 'Defragmented-copy publication safety',
        'why': 'The source must stay unchanged and only a fully checked candidate may become visible without replacing another creator.',
        'where': 'Copy, validation, link, directory-flush, and cleanup boundaries.',
        'impact': 'A race or flush failure could overwrite an existing output or publish a corrupt candidate.',
    },
    'defrag-negative': {
        'what': 'Unsafe defrag input rejection',
        'why': 'Invalid layouts, containers, links, and lock conflicts must be rejected without changing source bytes.',
        'where': 'Mutated images plus FIFO, symlink, hard-link, and advisory-lock cases.',
        'impact': 'Failing open could modify the wrong object or compound existing filesystem corruption.',
    },
    'defrag-transaction': {
        'what': 'Defrag host-death and rollback regressions',
        'why': 'Directory flush errors, parent death, and invalid journal objects must leave exact recovery possible.',
        'where': 'The journal owner and worker lifecycle around a disposable image.',
        'impact': 'An orphan worker or unsafe journal read could race recovery and damage the source.',
    },
    'defrag-upstream': {
        'what': 'Existing upstream corruption fixtures',
        'why': 'The checker used by defrag must still detect, repair, and cleanly reread the established fixture corpus.',
        'where': 'Repository fsck and upcase-table regression images.',
        'impact': 'Defrag validation would be unreliable if its checker regressed on known corruption.',
    },
    'defrag-metadata': {
        'what': 'Defrag metadata and boot-byte preservation',
        'why': 'Attributes, times, valid-data length, UTC offsets, and unrelated boot bytes are outside physical relocation.',
        'where': '512-byte and 4096-byte sector images with varied directory metadata.',
        'impact': 'A file may keep its contents but lose timestamps, flags, or valid-data semantics.',
    },
    'defrag-matrix': {
        'what': 'Defrag geometry and occupancy matrix',
        'why': 'Relocation must work across the selected sector, cluster, vendor, free-space, depth, and system-tail combinations.',
        'where': 'A factorial set of rootless generated exFAT images.',
        'impact': 'A layout-specific bug could pass ordinary seeds yet fail on deep or nearly full volumes.',
    },
    'defrag-driver': {
        'what': 'Linux exFAT driver defrag interoperability',
        'why': 'Kernel-created workloads must survive offline defrag and compare equal after a read-only remount.',
        'where': 'Private disposable loop images mounted by the Linux exFAT driver.',
        'impact': 'A rootless model pass alone cannot show that real driver-created metadata remains usable.',
    },
}

USER_EFFECTS = {
    'missing': 'A problem can reach users without a trustworthy test record explaining whether it was ever checked.',
    'orchestration': 'A storage feature may be shipped with an untested path, so the first complete test happens on somebody\'s own files.',
    'resize-library': 'After changing storage size, photos, downloads, apps, or recordings may disappear, open damaged, or use the wrong amount of space.',
    'resize-host': 'A mistyped size or damaged card may be modified instead of refused, making the original files harder to recover.',
    'resize-model': 'A USB drive, memory card, phone, or set-top box may show the new size but contain missing or corrupted personal files.',
    'resize-faults': 'After a flat battery, power cut, unplugged cable, or forced restart, the device may say the storage is unreadable or needs formatting.',
    'resize-large-faults': 'Large videos, offline maps, games, or TV recordings may be corrupted even when small files still look normal.',
    'resize-fsck': 'Running repair may delete recoverable files, keep reporting the same error, or leave the storage unusable.',
    'resize-counterexample': 'A healthy card may be reported as damaged, while repairing it can make devices reject its system metadata.',
    'resize-container': 'The computer may lose its partition table, stop booting, or show several partitions as one broken disk.',
    'resize-nofat': 'A device may reject a valid card or make intact photos and media appear to belong to damaged clusters.',
    'resize-signals': 'Cancelling the operation or shutting down the computer may leave the storage unable to mount on the next start.',
    'resize-compound': 'A power or storage error while cancelling may leave neither the old nor new size usable, even after retrying recovery.',
    'resize-driver': 'Linux or an embedded device may fail to remount the storage, lose files, or be unable to use the newly added free space.',
    'defrag-regressions': 'After an “optimize storage” operation, files may vanish, fail to open, or trigger a repair warning that did not exist before.',
    'defrag-model': 'Folders may still be listed normally while a photo, document, app file, or recording contains changed bytes.',
    'defrag-faults': 'A restart or unplug during optimization may leave the card or drive unreadable instead of safely returning to its old state.',
    'defrag-persistence': 'A real power loss may expose delayed or half-written data and make files corrupt only after the device starts again.',
    'defrag-publication': 'An existing backup may be overwritten, or a newly visible “optimized” copy may look complete but contain damaged data.',
    'defrag-negative': 'The tool may alter the wrong file, linked image, or already damaged volume instead of stopping with a clear error.',
    'defrag-transaction': 'A closed app may leave a background worker changing storage, so a later retry or repair races with unfinished work.',
    'defrag-upstream': 'A user asking the repair tool for help may lose recoverable data or remain stuck in a repeated repair loop.',
    'defrag-metadata': 'Files may keep their contents but suddenly have wrong dates, lose read-only/hidden flags, or appear truncated to an application.',
    'defrag-matrix': 'Optimization may work on one card but fail only on a particular phone, camera, disk size, or nearly full volume.',
    'defrag-driver': 'A computer, media box, or other Linux device may no longer mount the volume or play the files created before optimization.',
}


def described_intent(key):
    return INTENTS[key] | {'user': USER_EFFECTS[key]}


def suite_title(intent, source):
    return (f'What: {intent["what"]} | What the user notices: {intent["user"]} '
            f'[{source}]')


def load_json(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return {'status': 'FAIL', 'case': 'read results', 'error': f'{path}: {exc}'}


def rows_from(data):
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if not isinstance(data, dict):
        return []
    for key in ('tests', 'cases', 'steps'):
        if isinstance(data.get(key), list):
            return [row for row in data[key] if isinstance(row, dict)]
    if 'case' in data or 'name' in data:
        return [data]
    return []


def status_of(row):
    return str(row.get('status', 'FAIL')).upper()


def report_rows(result_path):
    data = load_json(result_path)
    cases_path = result_path.with_name('cases.jsonl')
    if cases_path.exists():
        rows = []
        try:
            rows = [json.loads(line) for line in cases_path.read_text().splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError) as exc:
            rows = [{'case': 'read case records', 'status': 'FAIL', 'error': str(exc)}]
    else:
        rows = rows_from(data)
    overall = status_of(data) if isinstance(data, dict) else 'PASS'
    if overall not in ('PASS', 'PASS_WITH_BLOCKERS') and not any(status_of(row) == 'FAIL' for row in rows):
        detail = data.get('error') or data.get('failure') or data.get('reason') if isinstance(data, dict) else None
        rows.append({'case': 'campaign completion', 'status': overall, 'error': detail or 'The campaign did not complete.'})
    if not rows:
        rows.append({'case': 'campaign result', 'status': overall,
                     'error': data.get('error') if isinstance(data, dict) else 'No test cases were recorded.'})
    return data, rows


def relative_parent(result_path, root):
    try:
        value = result_path.parent.relative_to(root)
        return str(value) if str(value) != '.' else root.name
    except ValueError:
        return str(result_path.parent)


def intent_key(profile, source, row):
    parts = set(Path(source).parts)
    case = str(row.get('case', row.get('name', '')))
    if profile == 'resize':
        for part, key in (
            ('upstream', 'resize-fsck'), ('fsck-sanitizers', 'resize-fsck'),
            ('counterexamples', 'resize-counterexample'), ('containers', 'resize-container'),
            ('inactive-fat', 'resize-nofat'), ('signals', 'resize-signals'),
            ('compound-cancel', 'resize-compound'), ('large-faults', 'resize-large-faults'),
            ('driver', 'resize-driver')):
            if part in parts:
                return key
        if case in ('fault', 'recovery-fault', 'persistent-storage-error',
                    'corrupt-and-wrong-commit', 'missing-wrong-corrupt-stale-journal'):
            return 'resize-faults'
        if case == 'model':
            return 'resize-model'
        if case.endswith('_tests'):
            return 'resize-library'
        return 'resize-host'
    for part, key in (
        ('baseline', 'defrag-regressions'), ('regressions', 'defrag-regressions'),
        ('faults', 'defrag-faults'), ('persistence', 'defrag-persistence'),
        ('publication', 'defrag-publication'), ('negative', 'defrag-negative'),
        ('transactions', 'defrag-transaction'), ('transaction_regressions', 'defrag-transaction'),
        ('upstream', 'defrag-upstream'), ('metadata', 'defrag-metadata'),
        ('matrix', 'defrag-matrix'), ('driver', 'defrag-driver')):
        if part in parts:
            return key
    if case in ('build', 'build-sanitizers') or 'steps' in row:
        return 'orchestration'
    return 'defrag-model' if 'model' in parts else 'orchestration'


def human(value):
    return str(value).replace('_', ' ').replace('-', ' ')


def byte_size(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return str(value)
    for unit, size in (('MiB', 1 << 20), ('KiB', 1 << 10)):
        if value >= size and value % size == 0:
            return f'{value // size} {unit}'
    return f'{value} B'


def case_name(row):
    label = row.get('name', row.get('case'))
    if label is None:
        for key in ('layout', 'version'):
            if key in row:
                label = f'{key} {row[key]}'
                break
    if label is None and 'seed' in row:
        label = 'model'
    label = human(label if label is not None else 'case')
    details = []
    if 'seed' in row:
        details.append(f'seed {row["seed"]}')
    for key in ('direction', 'mode'):
        if key in row and human(row[key]) not in label:
            details.append(human(row[key]))
    if 'position' in row:
        details.append(f'boundary {row["position"]}')
    if 'event' in row:
        details.append(human(row['event']))
    sector = row.get('sector_bytes', row.get('sector'))
    cluster = row.get('cluster_bytes', row.get('cluster'))
    if sector is not None:
        details.append(f'{byte_size(sector)} sectors')
    if cluster is not None:
        details.append(f'{byte_size(cluster)} clusters')
    count = row.get('iterations', row.get('operations'))
    if count is not None:
        details.append(f'{count} operations')
    return ' · '.join([label, *details])


def error_detail(row, intent):
    error = row.get('error', row.get('failure', row.get('reason', 'The recorded test status was not PASS.')))
    return (f'What: {intent["what"]}\nWhy: {intent["why"]}\nWhere: {intent["where"]}\n'
            f'If it failed: {intent["impact"]}\nWhat the user notices: {intent["user"]}\n\n'
            f'Evidence:\n{json.dumps(row, indent=2, default=str)}\n\n{error}')


def discover(root):
    if not root.exists():
        return []
    results = sorted(root.rglob('results.json'))
    combined = {path.parent for path in results if path.with_name('cases.jsonl').exists()}
    return [path for path in results
            if not any(parent in combined for parent in path.parents[1:])]


def generate(profile, inputs, output, summary=None):
    suites = []
    used_intents = {}
    for root in inputs:
        root = Path(root).resolve()
        paths = discover(root)
        if not paths:
            intent = described_intent('missing')
            suites.append((suite_title(intent, root.name), 'missing', intent,
                           [{'case': 'machine-readable results', 'status': 'FAIL',
                             'error': f'No results.json was found below {root}.'}]))
            used_intents['missing'] = intent
            continue
        for result_path in paths:
            data, rows = report_rows(result_path)
            source = relative_parent(result_path, root)
            groups = {}
            for row in rows:
                key = intent_key(profile, source, row)
                groups.setdefault(key, []).append(row)
            for key, group_rows in groups.items():
                intent = described_intent(key)
                used_intents[key] = intent
                suites.append((suite_title(intent, source), source, intent, group_rows))

    root_xml = ET.Element('testsuites')
    total_time = 0.0
    for title, source, intent, rows in suites:
        failures = sum(status_of(row) not in ('PASS', 'NOT_RUN') for row in rows)
        skipped = sum(status_of(row) == 'NOT_RUN' for row in rows)
        duration = sum(float(row.get('seconds', 0) or 0) for row in rows)
        total_time += duration
        suite = ET.SubElement(root_xml, 'testsuite', name=title, tests=str(len(rows)),
                              failures=str(failures), errors='0', skipped=str(skipped), time=f'{duration:.3f}')
        group = (f'Why: {intent["why"]} | Where: {intent["where"]} | '
                 f'If it failed: {intent["impact"]} | What the user notices: {intent["user"]}')
        for row in rows:
            testcase = ET.SubElement(suite, 'testcase', classname=group, name=case_name(row),
                                     time=f'{float(row.get("seconds", 0) or 0):.3f}')
            status = status_of(row)
            if status == 'NOT_RUN':
                ET.SubElement(testcase, 'skipped', message=str(row.get('reason', 'Required capability was not available.')))
            elif status != 'PASS':
                failure = ET.SubElement(testcase, 'failure', message=str(row.get('error', row.get('failure', status))))
                failure.text = error_detail(row, intent)
    root_xml.set('time', f'{total_time:.3f}')
    ET.indent(root_xml)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root_xml).write(output, encoding='utf-8', xml_declaration=True)

    if summary:
        summary = Path(summary)
        lines = ['## Qualification test intent', '',
                 'The JUnit check below lists the concrete cases. This table explains what each group protects.', '',
                 '| What | Why | Where | If it failed | What the user notices |',
                 '| --- | --- | --- | --- | --- |']
        for intent in used_intents.values():
            fields = [intent[key].replace('|', '\\|').replace('\n', ' ')
                      for key in ('what', 'why', 'where', 'impact', 'user')]
            lines.append('| ' + ' | '.join(fields) + ' |')
        with summary.open('a') as stream:
            stream.write('\n'.join(lines) + '\n')
    return root_xml


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=('resize', 'defrag'), required=True)
    parser.add_argument('--input', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--summary', type=Path)
    args = parser.parse_args(argv)
    generate(args.profile, args.input, args.output, args.summary)
    return 0


if __name__ == '__main__':
    sys.exit(main())
