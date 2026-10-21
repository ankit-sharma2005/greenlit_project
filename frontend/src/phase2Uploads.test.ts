/** @vitest-environment jsdom */

import { strToU8, zipSync } from 'fflate';
import { describe, expect, it } from 'vitest';
import { parseUploadRows } from './phase2Uploads';

describe('parseUploadRows', () => {
  it('reads tabular XLSX rows and their headers', async () => {
    const archive = zipSync({
      'xl/workbook.xml': strToU8(
        '<workbook xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="outputs" sheetId="1" r:id="rId1"/></sheets></workbook>',
      ),
      'xl/_rels/workbook.xml.rels': strToU8(
        '<Relationships><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
      ),
      'xl/worksheets/sheet1.xml': strToU8(
        '<worksheet><sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>id</t></is></c><c r="B1" t="inlineStr"><is><t>input</t></is></c><c r="C1" t="inlineStr"><is><t>output</t></is></c></row><row r="2"><c r="A2"><v>1</v></c><c r="B2" t="inlineStr"><is><t>hello</t></is></c><c r="C2" t="inlineStr"><is><t>world</t></is></c></row></sheetData></worksheet>',
      ),
    });
    const file = new File([], 'outputs.xlsx');
    Object.defineProperty(file, 'arrayBuffer', {
      value: () =>
        Promise.resolve(
          archive.buffer.slice(
            archive.byteOffset,
            archive.byteOffset + archive.byteLength,
          ) as ArrayBuffer,
        ),
    });

    await expect(parseUploadRows(file)).resolves.toEqual([
      { id: 1, input: 'hello', output: 'world' },
    ]);
  });
});
