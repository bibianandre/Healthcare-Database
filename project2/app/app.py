#!/usr/bin/python3
# Copyright (c) BDist Development Team
# Distributed under the terms of the Modified BSD License.
import os
from logging.config import dictConfig
import re

from flask import Flask, jsonify, request
from psycopg.rows import namedtuple_row
from psycopg_pool import ConnectionPool

# Use the DATABASE_URL environment variable if it exists, otherwise use the default.
# Use the format postgres://username:password@hostname/database_name to connect to the database.
DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://postgres:postgres@postgres/Saude")

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    kwargs={
        "autocommit": False,  # If True don’t start transactions automatically.
        "row_factory": namedtuple_row,
    },
    min_size=4,
    max_size=10,
    open=True,
    # check=ConnectionPool.check_connection,
    name="postgres_pool",
    timeout=5,
)

dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s:%(lineno)s - %(funcName)20s(): %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["wsgi"]},
    }
)

app = Flask(__name__)
app.config.from_prefixed_env()
log = app.logger

#Regex que verifica se o argumento dado para hora e valido
def is_time(h):
    pattern = r'^(2[0-3]|[01]\d):([0-5]\d):([0-5]\d)$'
    regex = re.compile(pattern)
    if regex.match(h):
        return True
    return False
    
#Regex que verifica se o argumento dado para data e valido
def is_date(d):
    pattern = r'^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$'
    regex = re.compile(pattern)
    if regex.match(d):
        return True
    return False

@app.route("/", methods=("GET",))
def clinic_index():
    #Mostra todas as clinicas

    with pool.connection() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                clinica = cur.execute(
                    """
                    SELECT nome, telefone, morada
                    FROM clinica;
                    """,
                    {},
                ).fetchall()
                log.debug(f"Found {cur.rowcount} rows.")

        return jsonify(clinica), 200


@app.route("/c/<clinica>/", methods=("GET",))
def clinica_especialidade(clinica):
    #Mostra todas as especialidades praticadas na clinica passada como argumento

    error = None
    
    if not all(x.isalnum() or x.isspace() for x in clinica):
        error = "O nome da clinica é invalido."

    if error is not None:
        return jsonify({"message": error, "status": "error"}), 400
    else:
        with pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    
                    cur.execute(
                            """
                            SELECT morada
                            FROM clinica
                            WHERE nome = %(clinica_)s;
                            """,
                            {"clinica_": clinica},
                        )
                    clinic_ = cur.fetchone()
                    if clinic_ is None:
                        return jsonify({"message": "A clínica indicada não está registada no sistema.", "status": "error"}), 404
                    
                    clinica = cur.execute(
                        """
                        SELECT DISTINCT m.especialidade
                        FROM medico m
                        JOIN trabalha t ON m.nif = t.nif
                        JOIN clinica c ON t.nome = c.nome
                        WHERE c.nome = %(clinica)s;
                        """,
                        {"clinica": clinica}
                    ).fetchall()
                    log.debug(f"Found {cur.rowcount} rows.")

            # At the end of the `connection()` context, the transaction is committed
            # or rolled back, and the connection returned to the pool.
            if len(clinica) == 0:
                return jsonify({"message": "Nao há especialidades para listar.", "status": "error"}), 404

            return jsonify(clinica), 200
        

#Endpoint nº3
@app.route(
    "/c/<clinica>/<especialidade>/",
    methods=(
        "GET",
    ),
)
def lista_medicos(clinica, especialidade):
    #Lista médicos de uma especialidade e os seus primeiros 3 horários (data e hora) 
    #disponiveis para marcacao de consulta

    error = None
    
    if not all(x.isalnum() or x.isspace() for x in clinica):
        error = "O nome da clínica não é válido."
    elif not all(x.isalnum() or x.isspace() for x in especialidade):
        error = "O nome da especialidade não é válido."

    if error is not None:
        return jsonify({"message": error, "status": "error"}), 400
    else:
        with pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    try:
                        cur.execute(
                            """
                            SELECT morada
                            FROM clinica
                            WHERE nome = %(clinica_)s;
                            """,
                            {"clinica_": clinica},
                        )
                        clinic_ = cur.fetchone()

                        if clinic_ is None:
                            return jsonify({"message": "A clínica indicada não está registada no sistema.", "status": "error"}), 404

                        cur.execute(
                            """
                            SELECT nif
                            FROM medico
                            WHERE especialidade = %(especialidade_)s;
                            """,
                            {"especialidade_": especialidade},
                        )
                        medicos_pretendidos = cur.fetchall()
                        if len(medicos_pretendidos) == 0:
                            return jsonify({"message": "Não há nenhum médico com a especialidade indicada.", "status": "error"}), 404
                        
                        cur.execute(
                            """
                            SELECT m.nif
                            FROM 
                                medico m,
                                trabalha t
                            WHERE t.nome = %(clinica_)s AND m.nif = t.nif AND m.especialidade = %(especialidade_)s;
                            """,
                            {"clinica_": clinica,
                            "especialidade_": especialidade},
                        )
                        especialidade_clinica_ = cur.fetchone()

                        if especialidade_clinica_ is None:
                            return jsonify({"message": "A clínica indicada não pratica a especialidade pretendida.", "status": "error"}), 404
                        
                        
                        datas_finais2=[]
                        for medico in medicos_pretendidos:
                        
                            datas_finais = cur.execute(
                                """
                                SELECT h.data, h.hora
                                FROM 
                                    horario h,
                                    trabalha t
                                WHERE h.data >= '2024-06-01' AND t.nif = %(nif_)s AND t.nome = %(clinica_)s AND (EXTRACT(DOW FROM h.data) = t.dia_da_semana)
                                EXCEPT (
                                    SELECT data, hora
                                FROM 
                                    consulta c
                                WHERE data >= '2024-06-01' AND nif = %(nif_)s AND nome = %(clinica_)s
                                    )
                                ORDER BY data ASC, hora ASC""",
                                {
                                    "clinica_": clinica,
                                    "nif_": medico[0]},
                            ).fetchall()
                            
                            if len(datas_finais)==0:
                                datas_finais2.append((medico[0], ['O médico não tem horários disponíveis para 2024.', '----']))
                                datas_finais2.append((medico[0], ['----', '----']))
                                datas_finais2.append((medico[0], ['----', '----']))
                            else:
                                datas_finais = [datas_finais[0], datas_finais[1], datas_finais[2]]
                                for data_hora in datas_finais:
                                    data_hora_serializable = [data_hora[0].strftime('%Y-%m-%d'), data_hora[1].strftime('%H:%M:%S')]
                                    datas_finais2.append((medico[0], data_hora_serializable))
                        dict_final ={}
                        index = 0
                        for medico in medicos_pretendidos:
                            # Filtra as datas e horas do atual medico
                            dates_for_nif = [dh[1] for dh in datas_finais2 if dh[0] == medico[0]]
                            # Adiciona o nif e as datas ao dicionario
                            dict_final[medico[0]] = dates_for_nif
                            
                            # The result of this statement is persisted immediately by the database
                            # because the connection is in autocommit mode.
                            log.debug(f"Updated {cur.rowcount} rows.")
                       
                        # The connection is returned to the pool at the end of the `connection()` context but,
                        # because it is not in a transaction state, no COMMIT is executed.

                        return jsonify(dict_final, {"status": "success"}), 200
                    except Exception as e:
                        return jsonify({"message": f"Ocorreu um erro: {str(e)}", "status": "error"}), 500

#Endpoint nº4
@app.route(
    "/a/<clinica>/registar/",
    methods=(
        "PUT",
        "POST",
    ),
)
def regista_consulta(clinica):
    #Regista uma consulta na base de dados 

    paciente = request.args.get("paciente")
    medico = request.args.get("medico")
    data = request.args.get("data")
    hora = request.args.get("hora")
    error = None
    
    if not paciente:
        error = "Indique o ssn do paciente."
        return jsonify({"message": error, "status": "error"}), 400
    if not medico:
        error = "Indique o nif do medico."
        return jsonify({"message": error, "status": "error"}), 400
    if not data:
        error = "Indique a data."
        return jsonify({"message": error, "status": "error"}), 400
    if not hora:
        error = "Indique a hora."
        return jsonify({"message": error, "status": "error"}), 400
    
    if not all(x.isalnum() or x.isspace() for x in clinica):
        error="O nome da clínica não é válido."
        return jsonify({"message": error, "status": "error"}), 400
    
    if not paciente.isdigit() or len(paciente) != 11:
        error="O ssn fornecido tem de ser um número inteiro de 11 dígitos."
        return jsonify({"message": error, "status": "error"}), 400
    
    if not medico.isdigit() or len(medico) != 9:
        error = "O nif fornecido tem de ser um número inteiro de 9 dígitos."
        return jsonify({"message": error, "status": "error"}), 400

    if not is_date(data):
        error = "A data fornecida é inválida."
    elif not is_time(hora):
        error = "A hora fornecida é inválida."

    if error is not None:
        return jsonify({"message": error, "status": "error"}), 400
    else:
        with pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    try:
                        cur.execute(
                            """
                            SELECT nome
                            FROM paciente
                            WHERE ssn = %(paciente)s;
                            """,
                            {"paciente": paciente},
                        )
                        paciente_ = cur.fetchone()

                        if paciente_ is None:
                            return jsonify({"message": "O paciente indicado não está registado no sistema.", "status": "error"}), 404

                        cur.execute(
                            """
                            SELECT nome
                            FROM medico
                            WHERE nif = %(medico)s;
                            """,
                            {"medico": medico},
                        )
                        medico_ = cur.fetchone()

                        if medico_ is None:
                            return jsonify({"message": "O médico indicado não está registado no sistema.", "status": "error"}), 404
                        
                        cur.execute(
                            """
                            SELECT morada
                            FROM clinica
                            WHERE nome = %(clinica_)s;
                            """,
                            {"clinica_": clinica},
                        )
                        clinic_ = cur.fetchone()

                        if clinic_ is None:
                            return jsonify({"message": "A clínica indicada não está registada no sistema.", "status": "error"}), 404
                        
                        
                        cur.execute(
                            """
                            SELECT hora
                            FROM horario
                            WHERE  data = %(data_)s AND data >= '2024-06-01';
                            """,
                            {"data_": data},
                        )
                        date_var_ = cur.fetchone()

                        if date_var_ is None:
                            return jsonify({"message": "A data da marcação não pode ser igual ou anterior à data atual.", "status": "error"}), 404

                        cur.execute(
                            """
                            SELECT nif
                            FROM consulta c
                            WHERE ssn = %(ssn_)s AND nif = %(nif_)s AND nome = %(clinica)s AND data = %(data_)s AND hora = %(hora_)s;
                            """,
                            {
                                "ssn_": paciente,
                                "nif_": medico,
                                "clinica": clinica,
                                "data_": data,
                                "hora_": hora},
                        )
                        medico_ = cur.fetchone()

                        if medico_ is not None:
                            return jsonify({"message": "A marcação que pretende registar já se encontra no sistema. Ação abortada.", "status": "error"}), 404

                        cur.execute(
                            """
                            SELECT nif
                            FROM consulta c
                            WHERE ssn = %(ssn_)s AND data = %(data_)s AND hora = %(hora_)s;
                            """,
                            {
                                "ssn_": paciente,
                                "nif_": medico,
                                "clinica": clinica,
                                "data_": data,
                                "hora_": hora},
                        )
                        medico_ = cur.fetchone()

                        if medico_ is not None:
                            return jsonify({"message": "O paciente já tem uma consulta marcada na mesma data, na mesma hora.", "status": "error"}), 404
                        
                        cur.execute(
                            """
                            SELECT nif
                            FROM consulta c
                            WHERE nif = %(nif_)s AND data = %(data_)s AND hora = %(hora_)s;
                            """,
                            {
                                "ssn_": paciente,
                                "nif_": medico,
                                "clinica": clinica,
                                "data_": data,
                                "hora_": hora},
                        )
                        medico_ = cur.fetchone()

                        if medico_ is not None:
                            return jsonify({"message": "O médico já tem uma consulta marcada na data e hora pedidas.", "status": "error"}), 404
                        cur.execute(
                            """
                            INSERT INTO consulta (ssn, nif, nome, data, hora, codigo_sns) 
                            VALUES (%(ssn_)s, %(nif_)s, %(clinica_)s, %(data_)s, %(hora_)s, NULL);
                            """,
                            {
                                "ssn_": paciente,
                                "nif_": medico,
                                "clinica_": clinica,
                                "data_": data,
                                "hora_": hora},
                        )
                        # The result of this statement is persisted immediately by the database
                        # because the connection is in autocommit mode.
                        log.debug(f"Updated {cur.rowcount} rows.")

                        if cur.rowcount == 0:
                            return (
                                jsonify({"message": "Falha ao registar consulta.", "status": "error"}),
                                404,
                            )

                        # The connection is returned to the pool at the end of the `connection()` context but,
                        # because it is not in a transaction state, no COMMIT is executed.

                        return jsonify({"message": "Consulta registada com sucesso.", "status": "success"}), 200
                    except Exception as e:
                        return jsonify({"message": f"Ocorreu um erro: {str(e)}", "status": "error"}), 500

#Endpoint nº5
@app.route(
    "/a/<clinica>/cancelar/",
    methods=(
        "DELETE",
        "POST",
    ),
)
def cancela_consulta(clinica):
    #Remove uma marcacao de consulta

    paciente = request.args.get("paciente")
    medico = request.args.get("medico")
    data = request.args.get("data")
    hora = request.args.get("hora")
    error = None
    
    if not paciente:
        error = "Indique o ssn de um paciente."
        return jsonify({"message": error, "status": "error"}), 400
    if not medico:
        error = "Indique o nif de um medico."
        return jsonify({"message": error, "status": "error"}), 400
    if not data:
        error = "Indique uma data."
        return jsonify({"message": error, "status": "error"}), 400
    if not hora:
        error = "Indique uma hora."
        return jsonify({"message": error, "status": "error"}), 400
    
    if not all(x.isalnum() or x.isspace() for x in clinica):
        error="O nome da clínica não é válido."
        return jsonify({"message": error, "status": "error"}), 400
    
    if not paciente.isdigit() or len(paciente) != 11:
        error = "O ssn fornecido tem de ser um número inteiro de 11 dígitos."
        return jsonify({"message": error, "status": "error"}), 400
    
    if not medico.isdigit() or len(medico) != 9:
        error = "O nif fornecido tem de ser um número inteiro de 9 dígitos."
        return jsonify({"message": error, "status": "error"}), 400

    if not is_date(data):
        error = "A data fornecida é inválida."  
    elif not is_time(hora):
        error = "A hora fornecida é inválida."  

    if error is not None:
        return jsonify({"message": error, "status": "error"}), 400
    else:
        with pool.connection() as conn:
            with conn.transaction():
                with conn.cursor() as cur:
                    try:
                        cur.execute(
                                """
                                SELECT nome
                                FROM paciente
                                WHERE ssn = %(paciente)s;
                                """,
                                {"paciente": paciente},
                            )
                        paciente_ = cur.fetchone()

                        if paciente_ is None:
                            return jsonify({"message": "O paciente indicado não está registado no sistema.", "status": "error"}), 404

                        cur.execute(
                                """
                                SELECT nome
                                FROM medico
                                WHERE nif = %(medico)s;
                                """,
                                {"medico": medico},
                            )
                        medico_ = cur.fetchone()

                        if medico_ is None:
                                return jsonify({"message": "O médico indicado não está registado no sistema.", "status": "error"}), 404
                            
                        cur.execute(
                            """
                            SELECT morada
                            FROM clinica
                            WHERE nome = %(clinica_)s;
                            """,
                            {"clinica_": clinica},
                        )
                        clinic_ = cur.fetchone()

                        if clinic_ is None:
                            return jsonify({"message": "A clínica indicada não está registada no sistema.", "status": "error"}), 404
                        
                        
                        cur.execute(
                            """
                            SELECT hora
                            FROM horario
                            WHERE  data = %(data_)s AND data >= '2024-06-01';
                            """,
                            {"data_": data},
                        )
                        date_var_ = cur.fetchone()

                        if date_var_ is None:
                            return jsonify({"message": "Não pode cancelar consultas que já ocorreram ou que irão ocorrer no dia atual.", "status": "error"}), 404

                        cur.execute(
                                """
                                SELECT codigo_sns, id
                                FROM consulta c
                                WHERE ssn = %(ssn_)s AND nif = %(nif_)s AND nome = %(clinica)s AND data = %(data_)s AND hora = %(hora_)s;
                                """,
                                {
                                    "ssn_": paciente,
                                    "nif_": medico,
                                    "clinica": clinica,
                                    "data_": data,
                                    "hora_": hora},
                            )
                        codigo_sns_ = cur.fetchone()

                        if codigo_sns_ is None:
                                return jsonify({"message": "A marcação indicada não existe no sistema.", "status": "error"}), 404
                        
                        
                        cur.execute(
                            """
                            DELETE FROM receita 
                            WHERE codigo_sns = %(codigo_sns_)s;
                            """,
                            {
                                "codigo_sns_":codigo_sns_[0]},
                        )
                        
                        cur.execute(
                            """
                            DELETE FROM observacao 
                            WHERE id = %(id_)s;
                            """,
                            {
                                "id_":codigo_sns_[1]},
                        )
                        
                        cur.execute(
                            """
                            DELETE FROM consulta 
                            WHERE ssn = %(ssn_)s AND nif = %(nif_)s AND nome = %(clinica)s AND data = %(data_)s AND hora = %(hora_)s;
                            """,
                            {
                                "ssn_": paciente,
                                "nif_": medico,
                                "clinica": clinica,
                                "data_": data,
                                "hora_": hora},
                        )
                        # The result of this statement is persisted immediately by the database
                        # because the connection is in autocommit mode.
                        log.debug(f"Updated {cur.rowcount} rows.")

                        if cur.rowcount == 0:
                            return (
                                jsonify({"message": "Falha ao cancelar consulta ", "status": "error"}),
                                404,
                            )

                        # The connection is returned to the pool at the end of the `connection()` context but,
                        # because it is not in a transaction state, no COMMIT is executed.

                        return jsonify({"message": "Consulta cancelada com sucesso.", "status": "success"}), 200
                    except Exception as e:
                        return jsonify({"message": f"Ocorreu um erro: {str(e)}", "status": "error"}), 500
                    

@app.route("/ping", methods=("GET",))
def ping():
    log.debug("ping!")
    return jsonify({"message": "pong!", "status": "success"})


if __name__ == "__main__":
    app.run()