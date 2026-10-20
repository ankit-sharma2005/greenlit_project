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

export async function parseUploadRows(
  file: Pick<File, 'name' | 'text'>,
): Promise<UploadedRow[]> {
  const text = await file.text();
  const extension = file.name.split('.').pop()?.toLowerCase();
  let rows: UploadedRow[];
  if (extension === 'csv') {
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
  } else {
    throw new Error('Choose a .csv, .json, or .jsonl file.');
  }
  if (!rows.length) throw new Error('The uploaded file has no data rows.');
  if (rows.length > 10000) {
    throw new Error('The uploaded file may contain at most 10,000 rows.');
  }
  return rows;
}
