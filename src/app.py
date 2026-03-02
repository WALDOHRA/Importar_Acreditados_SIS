from flask import Flask, render_template, request, jsonify, Response, stream_with_context
import pyodbc
import zipfile
import os
import shutil
import csv
import io
import time
import logging
from datetime import datetime
import traceback

app = Flask(__name__)

# LOGGING CONFIGURATION
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler() # Output to console (Docker logs)
    ]
)
logger = logging.getLogger(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
EXTRACT_FOLDER = 'temp_extract'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

if not os.path.exists(EXTRACT_FOLDER):
    os.makedirs(EXTRACT_FOLDER)

def get_db_connection(server, port, user, password, database):
    # Driver needs to match what is installed in Dockerfile (msodbcsql17)
    # Syntax for server with port is usually "server,port"
    conn_str = f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server},{port};DATABASE={database};UID={user};PWD={password};TrustServerCertificate=yes'
    return pyodbc.connect(conn_str)


def create_temp_table(cursor):
    """Creates the temp table for staging data."""
    cursor.execute("""
        IF OBJECT_ID('tempdb..#SisFiliacionesTemp') IS NOT NULL DROP TABLE #SisFiliacionesTemp;
        CREATE TABLE #SisFiliacionesTemp (
            idSiasis int, Codigo varchar(2), AfiliacionDisa varchar(3),
            AfiliacionTipoFormato varchar(2), AfiliacionNroFormato varchar(10),
            AfiliacionNroIntegrante varchar(2), DocumentoTipo varchar(1),
            CodigoEstablAdscripcion varchar(10), AfiliacionFecha datetime,
            Paterno varchar(40), Materno varchar(40), Pnombre varchar(70),
            Onombres varchar(70), Genero varchar(1), Fnacimiento datetime,
            IdDistritoDomicilio varchar(6), Estado varchar(1), Fbaja varchar(10),
            DocumentoNumero varchar(10), MotivoBaja varchar(70)
        )
    """)

def process_bulk(cursor, rows):
    """Inserts a batch of rows into the staging temp table."""
    sql_insert_temp = """
        INSERT INTO #SisFiliacionesTemp (
            idSiasis, Codigo, AfiliacionDisa, AfiliacionTipoFormato, AfiliacionNroFormato,
            AfiliacionNroIntegrante, DocumentoTipo, CodigoEstablAdscripcion,
            AfiliacionFecha, Paterno, Materno, Pnombre, Onombres,
            Genero, Fnacimiento, IdDistritoDomicilio, Estado, Fbaja,
            DocumentoNumero, MotivoBaja
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    cursor.fast_executemany = True
    cursor.executemany(sql_insert_temp, rows)

def finalize_import(cursor):
    """Merges data from temp table to final table and cleans up using T-SQL MERGE with deduplication."""
    sql_merge = """
        WITH DedupedSource AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY idSiasis, Codigo ORDER BY (SELECT NULL)) as rn
            FROM #SisFiliacionesTemp
        )
        MERGE INTO SisFiliaciones AS T
        USING (SELECT * FROM DedupedSource WHERE rn = 1) AS S
        ON T.idSiasis = S.idSiasis AND T.Codigo = S.Codigo
        WHEN MATCHED AND EXISTS (
            SELECT S.AfiliacionDisa, S.AfiliacionTipoFormato, S.AfiliacionNroFormato, S.AfiliacionNroIntegrante,
                   S.DocumentoTipo, S.CodigoEstablAdscripcion, S.AfiliacionFecha, S.Paterno, S.Materno,
                   S.Pnombre, S.Onombres, S.Genero, S.Fnacimiento, S.IdDistritoDomicilio, S.Estado,
                   S.Fbaja, S.DocumentoNumero, S.MotivoBaja
            EXCEPT
            SELECT T.AfiliacionDisa, T.AfiliacionTipoFormato, T.AfiliacionNroFormato, T.AfiliacionNroIntegrante,
                   T.DocumentoTipo, T.CodigoEstablAdscripcion, T.AfiliacionFecha, T.Paterno, T.Materno,
                   T.Pnombre, T.Onombres, T.Genero, T.Fnacimiento, T.IdDistritoDomicilio, T.Estado,
                   T.Fbaja, T.DocumentoNumero, T.MotivoBaja
        ) THEN
            UPDATE SET
                T.AfiliacionDisa = S.AfiliacionDisa,
                T.AfiliacionTipoFormato = S.AfiliacionTipoFormato,
                T.AfiliacionNroFormato = S.AfiliacionNroFormato,
                T.AfiliacionNroIntegrante = S.AfiliacionNroIntegrante,
                T.DocumentoTipo = S.DocumentoTipo,
                T.CodigoEstablAdscripcion = S.CodigoEstablAdscripcion,
                T.AfiliacionFecha = S.AfiliacionFecha,
                T.Paterno = S.Paterno,
                T.Materno = S.Materno,
                T.Pnombre = S.Pnombre,
                T.Onombres = S.Onombres,
                T.Genero = S.Genero,
                T.Fnacimiento = S.Fnacimiento,
                T.IdDistritoDomicilio = S.IdDistritoDomicilio,
                T.Estado = S.Estado,
                T.Fbaja = S.Fbaja,
                T.DocumentoNumero = S.DocumentoNumero,
                T.MotivoBaja = S.MotivoBaja
        WHEN NOT MATCHED BY TARGET THEN
            INSERT (
                idSiasis, Codigo, AfiliacionDisa, AfiliacionTipoFormato, AfiliacionNroFormato,
                AfiliacionNroIntegrante, DocumentoTipo, CodigoEstablAdscripcion,
                AfiliacionFecha, Paterno, Materno, Pnombre, Onombres,
                Genero, Fnacimiento, IdDistritoDomicilio, Estado, Fbaja,
                DocumentoNumero, MotivoBaja
            )
            VALUES (
                S.idSiasis, S.Codigo, S.AfiliacionDisa, S.AfiliacionTipoFormato, S.AfiliacionNroFormato,
                S.AfiliacionNroIntegrante, S.DocumentoTipo, S.CodigoEstablAdscripcion,
                S.AfiliacionFecha, S.Paterno, S.Materno, S.Pnombre, S.Onombres,
                S.Genero, S.Fnacimiento, S.IdDistritoDomicilio, S.Estado, S.Fbaja,
                S.DocumentoNumero, S.MotivoBaja
            );
    """
    cursor.execute(sql_merge)

    # 3. Cleanup
    cursor.execute("DROP TABLE #SisFiliacionesTemp")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/import', methods=['POST'])
def import_data():
    # 1. Retrieve parameters OUTSIDE the generator
    try:
        if 'file' not in request.files:
            return jsonify({'status': 'error', 'message': 'No file part'})
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'status': 'error', 'message': 'No selected file'})
            
        upload_folder = app.config['UPLOAD_FOLDER']

        server = request.form['server']
        port = request.form.get('port', '1433')
        user = request.form['user']
        password = request.form['password']
        zip_password = request.form.get('zip_password', '')
        delimiter = request.form.get('delimiter', ',')
        
        # Handle special char for Tab if sent as string "TAB" (optional, but good for UI)
        if delimiter == 'TAB': 
            delimiter = '\t'
        elif delimiter == 'OTHER':
            delimiter = request.form.get('other_delimiter', ',')
            if not delimiter: delimiter = ',' # Fallback to comma if empty

        if not file or not file.filename.endswith('.zip'):
             return jsonify({'status': 'error', 'message': 'Formato de archivo inválido. Debe ser .zip'})

        # Save File BEFORE generator starts to avoid "read of closed file" error
        # request context might close the file stream once the generator starts yielding
        filepath = os.path.join(upload_folder, file.filename)
        try:
            file.save(filepath)
        except Exception as e:
            logger.error(f"Error saving file: {e}")
            return jsonify({'status': 'error', 'message': f'Error guardando archivo: {str(e)}'})

    except Exception as e:
         return jsonify({'status': 'error', 'message': f'Error validando/guardando: {str(e)}'})

    def generate():
        def log_step(message, level="INFO"):
            """Helper to log to console and yield to frontend with timestamp"""
            timestamp = datetime.now().strftime("%H:%M:%S")
            full_msg = f"[{timestamp}] {message}"
            
            # Log to Backend (Console)
            if level == "ERROR":
                logger.error(message)
            else:
                logger.info(message)
                
            # Yield to Frontend (SSE)
            return f"data: Log: {full_msg}\n\n"

        try:
            # File is already saved at 'filepath'
            yield log_step("Archivo subido y guardado. Iniciando extracción...")

            try:
                # Extract ZIP
                yield log_step("Descomprimiendo archivo ZIP...")
                with zipfile.ZipFile(filepath, 'r') as zip_ref:
                    if zip_password:
                        zip_ref.extractall(EXTRACT_FOLDER, pwd=bytes(zip_password, 'utf-8'))
                    else:
                        zip_ref.extractall(EXTRACT_FOLDER)
                
                yield log_step("Archivo extraído correctamente.")

                extracted_files = os.listdir(EXTRACT_FOLDER)
                if not extracted_files:
                    yield f"data: Error: El ZIP está vacío.\n\n"
                    # Cleanup
                    try:
                        os.remove(filepath)
                    except: pass
                    return

                target_file = os.path.join(EXTRACT_FOLDER, extracted_files[0])
                yield log_step(f"Procesando archivo objetivo: {extracted_files[0]}")

                # Connect to DB
                yield log_step(f"Intentando conectar a SQL Server en {server}:{port}...")
                
                # Small delay to ensure UI updates
                time.sleep(0.5) 
                
                conn = get_db_connection(server, port, user, password, 'SIGH_EXTERNA')
                cursor = conn.cursor()
                yield log_step("Conexión a Base de Datos establecida.")

                # PHASE 1: Create Temp Table
                yield log_step("Creando tabla temporal en base de datos...")
                create_temp_table(cursor)
                conn.commit()

                processed_count = 0
                rows_buffer = []

                # Count total lines
                total_lines = 0
                yield log_step("Analizando archivo para estimar registros...")
                try:
                     with open(target_file, 'r', encoding='latin-1') as f:
                        for i, _ in enumerate(f): 
                            total_lines += 1
                except:
                    pass
                yield log_step(f"Total líneas estimadas: {total_lines}")

                # Start timer
                start_time = time.time()

                # PHASE 2: Bulk Insert into Temp Table
                with open(target_file, 'r', encoding='latin-1') as f:
                    reader = csv.reader(f, delimiter=delimiter)
                    
                    BATCH_SIZE = 6000
                    yield log_step(f"Iniciando carga a tabla temporal (Lote: {BATCH_SIZE})...")
                    
                    for row in reader:
                        if len(row) >= 20:
                            rows_buffer.append(row[:20])
                            processed_count += 1

                            if len(rows_buffer) >= BATCH_SIZE:
                                process_bulk(cursor, rows_buffer)
                                conn.commit()
                                process_percent = int((processed_count / total_lines) * 90) if total_lines > 0 else 0
                                yield f"data: Progress: {processed_count} en tabla temporal ({process_percent}%)\n\n"
                                rows_buffer = []

                    if rows_buffer:
                        process_bulk(cursor, rows_buffer)
                        conn.commit()

                # PHASE 3: Merge from Temp to Final
                yield log_step("Carga temporal finalizada. Iniciando migración a tabla final sisFiliaciones...")
                finalize_import(cursor)
                conn.commit()
                
                conn.close()
                
                # Final progress update 100%
                yield f"data: Progress: {processed_count} registros procesados (100%)\n\n"
                
                # Calculate duration
                elapsed_seconds = time.time() - start_time
                elapsed_minutes = round(elapsed_seconds / 60, 2)
                
                success_msg = f"Se importó correctamente {processed_count} registros en {elapsed_minutes} minutos."
                yield log_step(success_msg)
                yield f"data: Success: {success_msg}\n\n"

                # Cleanup
                yield log_step("Limpiando archivos temporales...")
                shutil.rmtree(EXTRACT_FOLDER)
                os.makedirs(EXTRACT_FOLDER)
                os.remove(filepath)
                yield log_step("Proceso finalizado.")

            except Exception as e:
                err_msg = f"Error Interno: {str(e)}"
                logger.error(err_msg)
                logger.error(traceback.format_exc())
                yield log_step(err_msg, level="ERROR")
                yield f"data: Error: {str(e)}\n\n"
                
        except Exception as e:
            logger.error(f"Fatal Error: {str(e)}")
            yield f"data: Error: {str(e)}\n\n"

    # Use stream_with_context to keep request valid
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=51423)
