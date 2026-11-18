"""Readable, paginated PDFs from an already verified report snapshot."""
from datetime import datetime
from io import BytesIO
import math
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph

NY = ZoneInfo('America/New_York')
W, H = A4
M, CW = 40, A4[0]-80
NAVY, TEXT, MUTED, TEAL, CYAN, GREEN, RED, AMBER, LINE, PAPER, PALE = map(HexColor,
    ['#0b1826','#13283c','#586b7d','#087e8b','#22d3ee','#127757','#b73f55','#946413','#dce5ee','#f5f8fb','#e8f4f3'])


def number(value, digits=2, signed=False):
    if isinstance(value, bool):
        return 'Sin dato'
    try:
        v=float(value)
        if not math.isfinite(v):
            return 'Sin dato'
        return (('+' if signed and v>0 else '')+f'{v:,.{digits}f}').replace(',','~').replace('.',',').replace('~','.')
    except (TypeError,ValueError):
        return 'Sin dato'


def stamp(value, short=True):
    try:
        date=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        if date.tzinfo is None:
            return 'Hora no verificada'
        return date.astimezone(NY).strftime('%H:%M NY' if short else '%d/%m/%Y %H:%M NY')
    except (TypeError,ValueError):
        return 'Hora no suministrada'


def safe_url(value):
    try:
        url=urlsplit(str(value))
        if url.scheme not in ('http','https') or not url.hostname or url.username or url.password:
            return None
        query=urlencode([(k,v) for k,v in parse_qsl(url.query) if k.lower() not in ('key','apikey','api_key','token','secret')])
        return urlunsplit((url.scheme,url.netloc,url.path,query,''))
    except (ValueError,TypeError):
        return None


class _Canvas(canvas.Canvas):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._pages=[]

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        count=len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setStrokeColor(LINE);self.setLineWidth(.6);self.line(M,38,W-M,38)
            self.setFillColor(MUTED);self.setFont('Helvetica',7.2)
            self.drawString(M,24,'MarketIntel · Fuentes y horas al corte · La cobertura incompleta no se extrapola.')
            self.setFillColor(TEAL);self.setFont('Helvetica-Bold',8)
            self.drawRightString(W-M,24,f'{self._pageNumber:02d} / {count:02d}')
            super().showPage()
        super().save()


class _Report:
    def __init__(self,report):
        self.r=report;self.stream=BytesIO();self.c=_Canvas(self.stream,pagesize=A4,pageCompression=1)
        self.c.setTitle(str(report.get('title') or 'MarketIntel'))
        self.c.setAuthor('MarketIntel')
        self.c.setSubject('Reporte de mercado · Diseño 6.5.2 · Datos y cobertura de una misma consulta')
        self.active=False;self.chapter='';self.subtitle=''

    def rect(self,x,y,w,h,fill=white,stroke=None,radius=0):
        self.c.setFillColor(fill);self.c.setStrokeColor(stroke or fill)
        if radius:self.c.roundRect(x,H-y-h,w,h,radius,fill=1,stroke=bool(stroke))
        else:self.c.rect(x,H-y-h,w,h,fill=1,stroke=bool(stroke))

    def text(self,x,y,value,size=10,color=TEXT,font='Helvetica',right=False):
        self.c.setFont(font,size);self.c.setFillColor(color)
        (self.c.drawRightString if right else self.c.drawString)(x,H-y-size,str(value))

    def paragraph(self,value,x,y,w,size=9.5,color=TEXT,bold=False,align=TA_LEFT,draw=True):
        content=escape(str('Sin dato verificado' if value is None or value=='' else value)).replace('\n','<br/>')
        p=Paragraph(content,ParagraphStyle('body',fontName='Helvetica-Bold' if bold else 'Helvetica',
            fontSize=size,leading=size*1.43,textColor=color,alignment=align))
        _,height=p.wrap(w,2000)
        if draw:p.drawOn(self.c,x,H-y-height)
        return height

    def page(self,title,subtitle):
        if self.active:self.c.showPage()
        self.active=True;self.chapter=title.split(' · continuación')[0];self.subtitle=subtitle
        self.rect(0,0,W,H)
        self.rect(0,0,W,149,NAVY)
        self.rect(M,28,26,26,CYAN,radius=7);self.text(M+5,33,'MI',12,NAVY,'Helvetica-Bold')
        self.text(M+35,31,'MarketIntel',14,white,'Helvetica-Bold')
        label='REPORTE DE APERTURA' if self.r.get('kind')=='opening' else 'REPORTE DE SESIÓN · 17:00 NY'
        self.text(W-M,36,label,8,HexColor('#a5bdce'),right=True)
        size=26
        while self.c.stringWidth(title,'Helvetica-Bold',size)>CW and size>16:size-=1
        self.text(M,70,title,size,white,'Helvetica-Bold')
        self.paragraph(subtitle,M,113,CW,9.1,HexColor('#b4c7d8'))
        self.text(M,164,'Sesión '+str(self.r.get('session_date',''))+' · Corte '+stamp(self.r.get('cutoff_at')),8.4,MUTED)
        if self.r.get('provenance'):
            self.paragraph(self.r['provenance'],M,179,CW,7.5,MUTED)

    def ensure(self,y,height):
        if y+height>790:
            self.page(self.chapter+' · continuación',self.subtitle)
            return 209
        return y

    def callout(self,title,body,y,fill=PALE,accent=TEAL):
        title_h=self.paragraph(title,0,0,CW-32,11,accent,True,draw=False)
        body_h=self.paragraph(body,0,0,CW-32,9.4,draw=False)
        height=title_h+body_h+35
        y=self.ensure(y,height)
        self.rect(M,y,CW,height,fill,radius=8);self.rect(M,y+12,3,height-24,accent)
        self.paragraph(title,M+16,y+12,CW-32,11,accent,True)
        self.paragraph(body,M+16,y+title_h+21,CW-32,9.4)
        return y+height

    def source(self,label,url,x,y,w):
        h=self.paragraph(label,x,y,w,7.6,MUTED)
        target=safe_url(url)
        if target:self.c.linkURL(target,(x,H-y-h,x+w,H-y),relative=0,thickness=0)
        return h

    def overview(self):
        closing=self.r.get('kind')=='closing'
        a=self.r['analysis']
        self.page('Así terminó la sesión' if closing else 'Antes de la campana',
                  'S&P 500, Nasdaq 100 y oro. Una lectura sencilla que conecta los datos disponibles.')
        self.rect(M,204,CW,122,NAVY,radius=10)
        self.text(M+16,219,'LECTURA AL CORTE · '+stamp(self.r.get('cutoff_at')),8,CYAN,'Helvetica-Bold')
        self.paragraph(a['headline'],M+16,242,CW-32,21,white,True)
        quotes=self.r.get('quotes') or []
        width=(CW-20)/3
        for i,q in enumerate(quotes[:3]):
            x=M+i*(width+10);y=340
            self.rect(x,y,width,103,PAPER,LINE,8)
            self.paragraph(q.get('label'),x+11,y+10,width-22,7.8,MUTED,True)
            price=number(q.get('price'));size=21
            while self.c.stringWidth(price,'Helvetica-Bold',size)>width-22 and size>13:size-=1
            self.text(x+11,y+33,price,size,TEXT,'Helvetica-Bold')
            color=RED if isinstance(q.get('change'),(int,float)) and q['change']<0 else GREEN
            if q.get('price') is not None:
                line=number(q.get('change'),signed=True)+' '+str(q.get('unit',''))+' ('+number(q.get('change_pct'),signed=True)+'%)'
                self.paragraph(line,x+11,y+63,width-22,8.2,color,True)
            self.paragraph(str(q.get('unit',''))+' · '+stamp(q.get('as_of')),x+11,y+86,width-22,7.4,MUTED)
        self.text(M,464,'Lo que necesitas saber',17,TEXT,'Helvetica-Bold')
        y=498
        for i,item in enumerate(a.get('key_points',[])[:3]):
            title_h=self.paragraph(item['title'],0,0,CW-29,10.6,bold=True,draw=False)
            body_h=self.paragraph(item['text'],0,0,CW-29,9.1,draw=False)
            y=self.ensure(y,title_h+body_h+23)
            self.text(M,y,str(i+1),11,TEAL,'Helvetica-Bold')
            self.paragraph(item['title'],M+28,y,CW-28,10.6,bold=True)
            self.paragraph(item['text'],M+28,y+title_h+7,CW-28,9.1,MUTED)
            y+=title_h+body_h+23
        body_h=self.paragraph(a['synthesis'],0,0,CW-32,9.4,draw=False)
        if max(y+3,710)+body_h+53<=792:
            self.callout('En una frase',a['synthesis'],max(y+3,710))

    def table(self,headers,rows,widths,y,aligns=None,compact=False):
        def header(top):
            self.rect(M,top,CW,32,NAVY,radius=5)
            x=M
            for i,(label,width) in enumerate(zip(headers,widths)):
                self.paragraph(label,x+8,top+10,width-16,7.1,white,True,align=(aligns[i] if aligns else TA_LEFT))
                x+=width
            return top+32
        y=self.ensure(y,70);y=header(y)
        for index,row in enumerate(rows):
            height=max(self.paragraph(value.get('text') if isinstance(value,dict) else value,0,0,width-16,9.5,
                    draw=False) + (13 if isinstance(value,dict) and value.get('sub') else 0)
                    for value,width in zip(row,widths))+(16 if compact else 20)
            if y+height>790:
                self.page(self.chapter+' · continuación',self.subtitle);y=header(209)
            self.rect(M,y,CW,height,PAPER if index%2==0 else white)
            x=M
            for i,(value,width) in enumerate(zip(row,widths)):
                cell=value if isinstance(value,dict) else {'text':value}
                self.paragraph(cell.get('text'),x+8,y+(8 if compact else 10),width-16,9.5,cell.get('color',TEXT),cell.get('bold',False),align=(aligns[i] if aligns else TA_LEFT))
                if cell.get('sub'):self.paragraph(cell['sub'],x+8,y+(24 if compact else 26),width-16,7.5,MUTED)
                x+=width
            y+=height
        return y

    def macro(self):
        for item in self.r.get('macro') or []:
            self.page('La publicación del día','Resultado, consenso y período anterior, con una explicación sencilla.')
            self.paragraph(item.get('title'),M,209,CW,17,TEAL,True)
            self.text(M,242,'Publicado: '+stamp(item.get('published_at'),False),9,MUTED)
            y=self.table(['Actual','Consenso','Anterior'],[[item.get('actual'),item.get('consensus') or 'Sin consenso verificado',item.get('previous') or 'Sin período anterior verificado']],[CW/3]*3,269)
            y=self.callout('Explicado fácil',item.get('explanation'),y+25)+24
            y=self.ensure(y,75);self.text(M,y,'Qué cambió en el mercado',17,TEXT,'Helvetica-Bold');y+=34
            reaction=item.get('market_reaction') or []
            if reaction:
                y=self.table(['Referencia','Antes del dato','Al corte','Cambio puntos'],[[r.get('label'),number(r.get('before')),number(r.get('price')),{'text':number(r.get('change'),signed=True),'color':RED if (r.get('change') or 0)<0 else GREEN,'bold':True}] for r in reaction],[CW*.31,CW*.23,CW*.23,CW*.23],y)
                for r in reaction:
                    y=self.ensure(y+10,25)
                    y+=self.paragraph(str(r.get('label'))+': '+stamp(r.get('before_at'))+' a '+stamp(r.get('as_of')),M,y,CW,8.4,MUTED)
            y=self.ensure(y+17,50);y+=self.paragraph(item.get('market_reaction_note') or 'No hay una ventana verificada anterior y posterior para describir la reacción al dato.',M,y,CW,9,MUTED)
            y=self.ensure(y+19,25);self.source(str(item.get('source','Fuente'))+' · comunicado de la publicación',item.get('source_url'),M,y,CW)

    def breadth(self):
        self.page('Cuántas suben y bajan','S&P 500 y Nasdaq 100. El color de la muestra y los valores que todavía no tienen un dato válido.')
        y=210
        for row in self.r.get('breadth') or []:
            y=self.ensure(y,249)
            total=row.get('total');valid=row.get('valid') or 0
            coverage=valid/total*100 if isinstance(total,(int,float)) and total>0 else None
            self.text(M,y,str(row.get('label','Índice')),18,TEXT,'Helvetica-Bold')
            self.text(W-M,y+6,'Cobertura '+number(coverage,1)+'%' if coverage is not None else 'Cobertura sin verificar',9,TEAL if coverage==100 else AMBER,'Helvetica-Bold',True)
            values=[row.get('up') if valid else None,row.get('down') if valid else None,row.get('unchanged') if valid else None,row.get('missing')]
            for i,(value,label,color) in enumerate(zip(values,['AL ALZA','A LA BAJA','SIN CAMBIO','SIN DATO'],[GREEN,RED,MUTED,AMBER])):
                x=M+i*(CW+8)/4;w=(CW-24)/4
                self.rect(x,y+39,w,74,PAPER,LINE,8)
                self.text(x+11,y+49,number(value,0),24 if value is not None else 15,color,'Helvetica-Bold')
                self.text(x+11,y+91,label,7.5,color,'Helvetica-Bold')
            self.rect(M,y+130,CW,12,HexColor('#e6ebef'),radius=4)
            if total and valid:
                x=M
                for value,color in zip(values,[GREEN,RED,HexColor('#9eacb9'),HexColor('#e2be77')]):
                    width=CW*max(0,min(total,value or 0))/total
                    if width:self.rect(x,y+130,width,12,color)
                    x+=width
            text=('Entre '+str(valid)+' cotizaciones válidas de '+str(total)+': '+number((row.get('up') or 0)/valid*100,1)+'% suben y '+number((row.get('down') or 0)/valid*100,1)+'% bajan.' if valid and total else 'No hay suficientes datos para calcular porcentajes de participación.')
            ph=self.paragraph(text,M,y+157,CW,9.3,bold=True)
            detail=('Faltan '+str(row.get('missing'))+' valores: los porcentajes anteriores corresponden a la muestra, no al índice completo.' if total and valid<total else 'El índice pondera cada componente; el número de acciones no equivale a su aporte en puntos.')
            self.paragraph(detail,M,y+164+ph,CW,8.8,MUTED)
            period='Precios: '+stamp(row.get('as_of'))
            if row.get('latest_as_of'):period+=' a '+stamp(row['latest_as_of'])
            self.text(M,y+212,period,7.5,MUTED)
            self.source(str(row.get('source') or 'Fuente no suministrada'),row.get('membership_source_url') or row.get('source_url'),M,y+226,CW)
            y+=270
        y=self.ensure(max(y,745),39)
        self.paragraph('El universo puede superar 500 o 100 valores porque algunas empresas tienen varias clases de acciones. Los índices ponderan esas acciones; con una muestra incompleta no se cierra el balance del conjunto. Los conteos de ambos índices no se suman.',M,y,CW,9,MUTED)

    def seven(self):
        closing=self.r.get('kind')=='closing'
        self.page('Las siete al cierre' if closing else 'Las siete bajo la lupa',
                  'Precio anterior, precio observado y cambio. Cada acción conserva la hora del dato mostrado.')
        self.text(M,211,'¿Cuánto se movió cada empresa?',17,TEXT,'Helvetica-Bold')
        self.paragraph('Precios en USD. '+('La tabla termina en el cierre regular; las cotizaciones posteriores se muestran aparte.' if closing else 'Premercado es el último precio verificado al corte; la apertura definitiva todavía puede cambiar.'),M,246,CW,9.3,MUTED)
        rows=[]
        for q in self.r.get('magnificent_seven') or []:
            color=RED if (q.get('change') or 0)<0 else GREEN
            rows.append([{'text':q.get('ticker'),'sub':q.get('name') or q.get('label'),'bold':True},number(q.get('previous')),{'text':number(q.get('price')),'bold':True},
                         {'text':number(q.get('change'),signed=True),'color':color},
                         {'text':number(q.get('change_pct'),signed=True)+'%' if q.get('change_pct') is not None else 'Sin dato','color':color,'bold':True},stamp(q.get('as_of'))])
        y=self.table(['Empresa','Anterior','Cierre' if closing else 'Premercado','Cambio USD','Cambio %','Hora'],rows,[CW*.19,CW*.16,CW*.17,CW*.16,CW*.15,CW*.17],294,[TA_LEFT,TA_RIGHT,TA_RIGHT,TA_RIGHT,TA_RIGHT,TA_RIGHT],compact=True)
        a=self.r['analysis']
        if not closing:
            y=self.callout(a['seven_title'],a['seven_text'],y+23)+13
        else:
            y+=15
        sources=sorted(set(str(q.get('source') or 'Fuente no suministrada') for q in self.r.get('magnificent_seven',[])))
        y=self.ensure(y,25);y+=self.paragraph('Fuente: '+', '.join(sources)+'. Los datos con hora no verificada quedan identificados como ausentes.',M,y,CW,8,MUTED)
        for q in self.r.get('quotes') or []:
            if q.get('reason'):
                y=self.ensure(y+8,30);y+=self.paragraph(str(q.get('label'))+': '+str(q['reason']),M,y,CW,8,MUTED)
        if closing:
            events=self.r.get('watchlist_reports') or []
            published={r.get('ticker') for r in events if r.get('status')=='published'}
            pending=[r for r in events if r.get('status')=='pending' and r.get('ticker') not in published]
            pending_symbols={r.get('ticker') for r in pending}
            unknown=set(self.r.get('watchlist') or [])-published-pending_symbols
            count=len(self.r.get('watchlist') or [])
            coverage=(f'{count} símbolos: {len(published)} con publicación confirmada, {len(pending_symbols)} pendientes y {len(unknown)} sin verificar. ')
            if count>12:coverage+='La búsqueda individual de noticias cubre hasta 12 empresas; la agenda adicional depende de su fuente. '
            if pending:
                text='; '.join(str(r.get('ticker'))+': '+str(r.get('summary') or 'Pendiente al corte') for r in pending[:2])
                self.callout('Pendientes de tu watchlist',coverage+text,y+15,HexColor('#fff5df'),AMBER)
            else:
                text='La lista está vacía.' if not count else coverage+('Las publicaciones confirmadas se detallan a continuación.' if published else 'No se recibió una publicación confirmada; los estados sin verificar no confirman ausencia de resultados.')
                self.callout('Tu watchlist al corte',text,y+15)

    def watchlist(self):
        events=self.r.get('watchlist_reports') or []
        published=[r for r in events if r.get('status')=='published']
        published_symbols={r.get('ticker') for r in published}
        pending=[r for r in events if r.get('status')=='pending' and r.get('ticker') not in published_symbols]
        others=pending[2:]
        if not published and not others:return
        self.page('Resultados en tu watchlist' if published else 'Agenda de tu watchlist',
                  'Publicaciones verificadas hasta el corte. Los movimientos posteriores al cierre se mantienen separados.' if published else
                  'Publicaciones pendientes al corte, sin anticipar su resultado.')
        y=210
        for item in published:
            title=str(item.get('ticker',''))+' · '+str(item.get('title') or 'Publicación')
            title_h=self.paragraph(title,0,0,CW-28,12,bold=True,draw=False)
            summary=str(item.get('summary') or 'Consultar publicación original.')
            summary_h=self.paragraph(summary,0,0,CW-28,9.4,draw=False)
            height=title_h+summary_h+(120 if item.get('post_price') is not None else 80)
            y=self.ensure(y,height+18)
            self.rect(M,y,CW,height,PAPER,LINE,8)
            self.paragraph(title,M+14,y+12,CW-28,12,TEAL,True)
            top=y+title_h+23
            self.text(M+14,top,'Publicado: '+stamp(item.get('published_at'),False),8,MUTED);top+=23
            top+=self.paragraph(summary,M+14,top,CW-28,9.4)
            if item.get('post_price') is not None:
                self.text(M+14,top+13,'Después del cierre: '+number(item['post_price'])+' USD · '+number(item.get('post_change_pct'),signed=True)+'%',11,TEAL,'Helvetica-Bold')
                self.text(M+14,top+31,'Observado: '+stamp(item.get('post_as_of')),8,MUTED);top+=41
            self.source(str(item.get('source') or 'Publicación original'),item.get('source_url'),M+14,top+13,CW-28)
            y+=height+18
        for item in others:
            y=self.callout(str(item.get('ticker'))+' · Pendiente',item.get('summary'),y+8,HexColor('#fff5df'),AMBER)+12

    def build(self):
        self.overview();self.macro();self.breadth();self.seven();self.watchlist()
        if self.active:self.c.showPage()
        self.c.save()
        return self.stream.getvalue()


def render_report_pdf(report):
    # Lazy import keeps the renderer usable directly while avoiding a module
    # import cycle with the report builder's public render_report_pdf wrapper.
    if not isinstance(report.get('analysis'),dict):
        from marketintel_reports import explain_report
        report=dict(report,analysis=explain_report(report))
    return _Report(report).build()
