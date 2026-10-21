export type UploadedRow = Record<string, unknown>;

function csvRows(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = '';
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (quoted) {
      if (character === '"' && text[index + 1] === '"') {
        field += '"';
        index += 1;
      } else if (character === '"') {
        quoted = false;
      } else {
        field += character;
      }
    } else if (character === '"' && field.length === 0) {
      quoted = true;
    } else if (character === ',') {
      row.push(field);
      field = '';
    } else if (character === '\n' || character === '\r') {
      if (character === '\r' && text[index + 1] === '\n') index += 1;
      row.push(field);
      if (row.some((value) => value.trim() !== '')) rows.push(row);
      row = [];
      field = '';
    } else {
      field += character;
    }
  }
  if (quoted)
    throw new Error('The CSV file contains an unclosed quoted field.');
  row.push(field);
  if (row.some((value) => value.trim() !== '')) rows.push(row);
  return rows;
}

function isRecord(value: unknown): value is UploadedRow {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readFileArrayBuffer(file: File): Promise<ArrayBuffer> {
  if (typeof file.arrayBuffer === 'function') return file.arrayBuffer();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (reader.result instanceof ArrayBuffer) resolve(reader.result);
      else reject(new Error('The XLSX file could not be read.'));
    };
    reader.onerror = () =>
      reject(reader.error ?? new Error('The XLSX file could not be read.'));
    reader.readAsArrayBuffer(file);
  });
}

export async function parseUploadRows(file: File): Promise<UploadedRow[]> {
  const extension = file.name.split('.').pop()?.toLowerCase();
  let rows: UploadedRow[] = [];
  if (extension === 'csv') {
    const text = await file.text();
    const [headerRow, ...dataRows] = csvRows(text);
    if (!headerRow?.length)
      throw new Error('The CSV file has no column header.');
    const headers = headerRow.map((header) => header.trim());
    if (headers.some((header) => !header)) {
      throw new Error('Every CSV column must have a header.');
    }
    if (new Set(headers).size !== headers.length) {
      throw new Error('CSV column headers must be unique.');
    }
    rows = dataRows.map((values) =>
      Object.fromEntries(
        headers.map((header, index) => [header, values[index] ?? '']),
      ),
    );
  } else if (extension === 'jsonl') {
    const text = await file.text();
    rows = text
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line, index) => {
        let value: unknown;
        try {
          value = JSON.parse(line) as unknown;
        } catch {
          throw new Error(`JSONL line ${index + 1} is not valid JSON.`);
        }
        if (!isRecord(value)) {
          throw new Error(`JSONL line ${index + 1} must be a JSON object.`);
        }
        return value;
      });
  } else if (extension === 'json') {
    const text = await file.text();
    let value: unknown;
    try {
      value = JSON.parse(text) as unknown;
    } catch {
      throw new Error('The JSON file is not valid JSON.');
    }
    if (!Array.isArray(value) || !value.every(isRecord)) {
      throw new Error('The JSON file must contain an array of objects.');
    }
    rows = value;
  } else if (extension === 'xlsx') {
    if (file.size > 20_000_000) {
      throw new Error('The XLSX file may be at most 20 MB.');
    }
    const { strFromU8, unzipSync } = await import('fflate');
    const archive = unzipSync(new Uint8Array(await readFileArrayBuffer(file)));
    const workbookXml = archive['xl/workbook.xml'];
    const relationshipsXml = archive['xl/_rels/workbook.xml.rels'];
    if (!workbookXml || !relationshipsXml) {
      throw new Error('The XLSX file is missing workbook metadata.');
    }
    const workbookDocument = parseXml(strFromU8(workbookXml));
    const relationshipsDocument = parseXml(strFromU8(relationshipsXml));
    const firstSheet = elementsByLocalName(workbookDocument, 'sheet')[0];
    const relationshipId =
      firstSheet?.getAttribute('r:id') ?? firstSheet?.getAttribute('id');
    const relationship = elementsByLocalName(
      relationshipsDocument,
      'Relationship',
    ).find((item) => item.getAttribute('Id') === relationshipId);
    const target = relationship?.getAttribute('Target');
    if (!target) throw new Error('The XLSX file contains no worksheets.');
    const sheetPath = target.startsWith('/')
      ? target.slice(1)
      : `xl/${target.replace(/^\.\//, '')}`;
    const sheetXml = archive[sheetPath];
    if (!sheetXml)
      throw new Error('The first XLSX worksheet could not be read.');
    const sheetDocument = parseXml(strFromU8(sheetXml));
    const sharedStringsXml = archive['xl/sharedStrings.xml'];
    const sharedStrings = sharedStringsXml
      ? elementsByLocalName(parseXml(strFromU8(sharedStringsXml)), 'si').map(
          (item) =>
            elementsByLocalName(item, 't')
              .map((text) => text.textContent ?? '')
              .join(''),
        )
      : [];
    const worksheetRows = elementsByLocalName(sheetDocument, 'row');
    const headerRow = worksheetRows.find(
      (row) => row.getAttribute('r') === '1',
    );
    const headerCells = headerRow ? elementsByLocalName(headerRow, 'c') : [];
    const headerValues = new Map<number, string>();
    headerCells.forEach((cell) => {
      const index = columnIndex(cell.getAttribute('r') ?? '');
      if (index > 0) {
        headerValues.set(
          index,
          String(readXlsxCell(cell, sharedStrings)).trim(),
        );
      }
    });
    const lastColumn = Math.max(0, ...headerValues.keys());
    const headers = Array.from(
      { length: lastColumn },
      (_, index) => headerValues.get(index + 1) ?? '',
    );
    if (!headers.length || headers.some((header) => !header)) {
      throw new Error('Every XLSX column must have a header.');
    }
    if (new Set(headers).size !== headers.length) {
      throw new Error('XLSX column headers must be unique.');
    }
    worksheetRows.forEach((row) => {
      if (row.getAttribute('r') === '1') return;
      const record: UploadedRow = Object.fromEntries(
        headers.map((header) => [header, '']),
      );
      elementsByLocalName(row, 'c').forEach((cell) => {
        const index = columnIndex(cell.getAttribute('r') ?? '') - 1;
        if (index >= 0 && headers[index]) {
          record[headers[index]] = readXlsxCell(cell, sharedStrings);
        }
      });
      if (Object.values(record).some((value) => value !== ''))
        rows.push(record);
    });
  } else {
    throw new Error('Choose a .csv, .json, .jsonl, or .xlsx file.');
  }

  function parseXml(source: string): Document {
    const document = new DOMParser().parseFromString(source, 'application/xml');
    if (document.getElementsByTagName('parsererror').length > 0) {
      throw new Error('The XLSX file contains invalid workbook data.');
    }
    return document;
  }

  function elementsByLocalName(
    parent: Document | Element,
    localName: string,
  ): Element[] {
    return Array.from(parent.getElementsByTagName('*')).filter(
      (element) => element.localName === localName,
    );
  }

  function columnIndex(cellReference: string): number {
    const letters = /^[A-Z]+/i.exec(cellReference)?.[0].toUpperCase() ?? '';
    return [...letters].reduce(
      (index, letter) => index * 26 + letter.charCodeAt(0) - 64,
      0,
    );
  }

  function readXlsxCell(
    cell: Element,
    sharedStrings: string[],
  ): string | number | boolean {
    const value = elementsByLocalName(cell, 'v')[0]?.textContent ?? '';
    const type = cell.getAttribute('t');
    if (type === 's') {
      const sharedValue = sharedStrings[Number(value)];
      return sharedValue ?? '';
    }
    if (type === 'inlineStr') {
      return elementsByLocalName(cell, 't')
        .map((text) => text.textContent ?? '')
        .join('');
    }
    if (type === 'b') return value === '1';
    if (value === '') return '';
    const number = Number(value);
    return Number.isFinite(number) && type !== 'str' ? number : value;
  }
  if (!rows.length) throw new Error('The uploaded file has no data rows.');
  if (rows.length > 10000) {
    throw new Error('The uploaded file may contain at most 10,000 rows.');
  }
  return rows;
}
