// SQLite (built into Bun as bun:sqlite) and migrations: every migrations/NNN_*.sql not applied
// yet runs once, in order, when the backend starts. Never edit an applied migration: add one.
import { Database } from "bun:sqlite";
import { readdirSync, readFileSync } from "node:fs";

export function openDb(file: string): Database {
  const db = new Database(file, { strict: true });
  db.run("PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;");
  migrate(db);
  return db;
}

function migrate(db: Database): void {
  const dir = `${import.meta.dir}/migrations`;
  const files = readdirSync(dir)
    .filter((n) => /^\d+_.*\.sql$/.test(n))
    .sort();
  const row = db.query("PRAGMA user_version").get() as { user_version: number };
  for (let i = row.user_version; i < files.length; i++) {
    db.run("BEGIN");
    try {
      db.run(readFileSync(`${dir}/${files[i]}`, "utf8"));
      db.run(`PRAGMA user_version = ${i + 1}`);
      db.run("COMMIT");
    } catch (e) {
      db.run("ROLLBACK");
      throw new Error(`migration ${files[i]} failed: ${e}`);
    }
  }
}
