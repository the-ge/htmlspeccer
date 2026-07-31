#!/usr/bin/env node

'use strict';

const fs = require('node:fs');
const path = require('node:path');

const root = process.cwd();

const rawDataDir = path.join(root, '.dev/data/raw');
const readmePath = path.join(root, 'README.md');

let readme = fs.readFileSync(readmePath, 'utf8');

for (const file of fs.readdirSync(rawDataDir).sort()) {
    if (!file.endsWith('.time')) {
        continue;
    }

    const marker = `${path.basename(file, '.time').toUpperCase()}_LAST_UPDATED`;
    const timestamp = fs.readFileSync(path.join(rawDataDir, file), 'utf8').trim();

    const regex = new RegExp(
        `(<!-- ${marker}:START -->)([\\s\\S]*?)(<!-- ${marker}:END -->)`,
        'g',
    );

    if (!regex.test(readme)) {
        throw new Error(`Marker "${marker}" not found in README.md.`);
    }

    readme = readme.replace(regex, `$1${timestamp}$3`);
}

fs.writeFileSync(readmePath, readme);