import { MigrationInterface, QueryRunner } from 'typeorm';
import { DatabaseTypeEnum } from '@gauzy/config';
import * as chalk from 'chalk';

export class AddEmployeeCode1785200000000 implements MigrationInterface {
	name = 'AddEmployeeCode1785200000000';

	/**
	 * Up Migration
	 *
	 * Adds `employee.employeeCode` — a human-chosen identifier (EMP001, YG-014, a
	 * payroll number) that an operator types when creating an employee, rather than
	 * the generated UUID.
	 *
	 * Two decisions worth stating, because both are load-bearing:
	 *
	 * (1) NULLABLE. Every employee that already exists has no code, and a NOT NULL
	 *     column cannot be added to a populated table without inventing a value for
	 *     each existing row. Backfilling identifiers nobody chose would defeat the
	 *     point of the field, so existing employees keep NULL until someone sets one.
	 *
	 * (2) UNIQUE PER ORGANISATION, not globally. Two organisations in the same
	 *     tenant may both legitimately use "EMP001". The partial index skips NULLs,
	 *     so any number of employees may have no code while the ones that do are
	 *     still guaranteed distinct within their organisation.
	 *
	 * The unique index is created only on Postgres and SQLite, which both support
	 * partial indexes. MySQL does not, and there its UNIQUE index would treat NULLs
	 * as distinct anyway — which happens to give the same behaviour, so the plain
	 * unique index below is equivalent for our purposes.
	 *
	 * @param queryRunner
	 */
	public async up(queryRunner: QueryRunner): Promise<void> {
		console.log(chalk.yellow(this.name + ' start running!'));

		switch (queryRunner.connection.options.type as DatabaseTypeEnum) {
			case DatabaseTypeEnum.sqlite:
			case DatabaseTypeEnum.betterSqlite3:
				await this.sqliteUpQueryRunner(queryRunner);
				break;
			case DatabaseTypeEnum.postgres:
				await this.postgresUpQueryRunner(queryRunner);
				break;
			case DatabaseTypeEnum.mysql:
				await this.mysqlUpQueryRunner(queryRunner);
				break;
			default:
				throw new Error(`Unsupported database: ${queryRunner.connection.options.type}`);
		}
	}

	/**
	 * Down Migration
	 *
	 * @param queryRunner
	 */
	public async down(queryRunner: QueryRunner): Promise<void> {
		switch (queryRunner.connection.options.type as DatabaseTypeEnum) {
			case DatabaseTypeEnum.sqlite:
			case DatabaseTypeEnum.betterSqlite3:
				await this.sqliteDownQueryRunner(queryRunner);
				break;
			case DatabaseTypeEnum.postgres:
				await this.postgresDownQueryRunner(queryRunner);
				break;
			case DatabaseTypeEnum.mysql:
				await this.mysqlDownQueryRunner(queryRunner);
				break;
			default:
				throw new Error(`Unsupported database: ${queryRunner.connection.options.type}`);
		}
	}

	/**
	 * PostgresDB Up Migration
	 *
	 * @param queryRunner
	 */
	public async postgresUpQueryRunner(queryRunner: QueryRunner): Promise<void> {
		await queryRunner.query(`ALTER TABLE "employee" ADD COLUMN IF NOT EXISTS "employeeCode" character varying(64)`);
		await queryRunner.query(
			`CREATE UNIQUE INDEX IF NOT EXISTS "IDX_employee_organization_employeeCode"
			 ON "employee" ("organizationId", "employeeCode")
			 WHERE "employeeCode" IS NOT NULL`
		);
	}

	/**
	 * PostgresDB Down Migration
	 *
	 * @param queryRunner
	 */
	public async postgresDownQueryRunner(queryRunner: QueryRunner): Promise<void> {
		await queryRunner.query(`DROP INDEX IF EXISTS "IDX_employee_organization_employeeCode"`);
		await queryRunner.query(`ALTER TABLE "employee" DROP COLUMN IF EXISTS "employeeCode"`);
	}

	/**
	 * SqliteDB and BetterSQlite3DB Up Migration
	 *
	 * @param queryRunner
	 */
	public async sqliteUpQueryRunner(queryRunner: QueryRunner): Promise<void> {
		await queryRunner.query(`ALTER TABLE "employee" ADD COLUMN "employeeCode" varchar(64)`);
		await queryRunner.query(
			`CREATE UNIQUE INDEX IF NOT EXISTS "IDX_employee_organization_employeeCode"
			 ON "employee" ("organizationId", "employeeCode")
			 WHERE "employeeCode" IS NOT NULL`
		);
	}

	/**
	 * SqliteDB and BetterSQlite3DB Down Migration
	 *
	 * @param queryRunner
	 */
	public async sqliteDownQueryRunner(queryRunner: QueryRunner): Promise<void> {
		await queryRunner.query(`DROP INDEX IF EXISTS "IDX_employee_organization_employeeCode"`);
		await queryRunner.query(`ALTER TABLE "employee" DROP COLUMN "employeeCode"`);
	}

	/**
	 * MySQL Up Migration
	 *
	 * @param queryRunner
	 */
	public async mysqlUpQueryRunner(queryRunner: QueryRunner): Promise<void> {
		await queryRunner.query(`ALTER TABLE \`employee\` ADD \`employeeCode\` varchar(64) NULL`);
		await queryRunner.query(
			`CREATE UNIQUE INDEX \`IDX_employee_organization_employeeCode\`
			 ON \`employee\` (\`organizationId\`, \`employeeCode\`)`
		);
	}

	/**
	 * MySQL Down Migration
	 *
	 * @param queryRunner
	 */
	public async mysqlDownQueryRunner(queryRunner: QueryRunner): Promise<void> {
		await queryRunner.query(`DROP INDEX \`IDX_employee_organization_employeeCode\` ON \`employee\``);
		await queryRunner.query(`ALTER TABLE \`employee\` DROP COLUMN \`employeeCode\``);
	}
}
