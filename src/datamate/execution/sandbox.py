import threading

import duckdb

from datamate.core import BusinessContext, Candidate, ExecResult


def execute(context: BusinessContext, candidate: Candidate, timeout: float = 30) -> ExecResult:
    result = ExecResult(candidate)
    if timeout <= 0:
        result.error = "SQL timeout"
        return result
    connection = duckdb.connect(str(context.database), read_only=True, config={
        "enable_external_access": "false", "autoinstall_known_extensions": "false",
        "autoload_known_extensions": "false", "threads": "1", "memory_limit": "512MB",
    })
    timer = threading.Timer(timeout, connection.interrupt)
    try:
        statements = connection.extract_statements(candidate.code)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("Only one SELECT statement is allowed")
        timer.start()
        connection.execute(candidate.code)
        result.columns = [column[0] for column in connection.description]
        result.rows = [list(row) for row in connection.fetchmany(10001)]
        if len(result.rows) > 10000:
            raise ValueError("Result exceeds 10000 rows")
    except Exception as error:
        result.error = str(error)
    finally:
        timer.cancel()
        if timer.ident is not None:
            timer.join()
        connection.close()
    return result
