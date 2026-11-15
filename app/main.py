"""FastAPI 网页入口：上传/粘贴 CSV，指定进水点与出水点，核查管网守恒可行性。"""
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from . import solver

app = FastAPI(title="水厂支管流量入仓前核查")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

MAX_CSV_BYTES = 256 * 1024  # 12 条管段的 CSV 极小，超限视为异常文件

SAMPLE_CSV = """管段编号,起点,终点,流量下限,流量上限
P1,S,A,0,10
P2,S,B,2,5
P3,A,B,0,3
P4,A,T,0,10
P5,B,T,0,6
"""


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/check", response_class=HTMLResponse)
async def check(
    request: Request,
    file: UploadFile | None = File(default=None),
    pasted: str = Form(default=""),
    source: str = Form(default=""),
    sink: str = Form(default=""),
):
    ctx = {
        "request": request,
        "source": source.strip(),
        "sink": sink.strip(),
        "pasted": pasted,
    }
    try:
        if file is not None and file.filename:
            data = await file.read()
            if len(data) > MAX_CSV_BYTES:
                raise solver.InputError("CSV 文件过大（上限 256 KB）。")
            text = data.decode("utf-8-sig")  # 兼容带 BOM 的 Excel 导出
        elif pasted.strip():
            text = pasted
        else:
            raise solver.InputError("请上传 CSV 文件，或将 CSV 内容粘贴到文本框。")

        pipes = solver.parse_csv(text)
        ctx["result"] = solver.solve(pipes, ctx["source"], ctx["sink"])
    except UnicodeDecodeError:
        ctx["error"] = "输入错误：文件编码无法识别，请使用 UTF-8 编码的 CSV。"
    except solver.InputError as exc:
        ctx["error"] = f"输入错误：{exc}"
    return templates.TemplateResponse("index.html", ctx)


@app.get("/sample.csv")
async def sample_csv():
    return Response(
        SAMPLE_CSV,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=sample.csv"},
    )
