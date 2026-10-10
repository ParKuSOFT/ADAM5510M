#include "5510drv.h"

//Сигналы на обмотку двигателей
unsigned char Signal[2] = {0, 1};
unsigned char Work[2] = {0, 1};
//Сигнал состояния пера и кнопки Stand_By
unsigned char Stand_By = 0;

//Переменные для номеров слотов
unsigned char _5050_0 = 0;
unsigned char _5050_1 = 1;

//Текущие координаты пера (мм)
int prevX = 0;
int prevY = 0;
//Текущая фаза каждого мотора (0..3)
int phX = 0;
int phY = 0;

//Декларирование функций
void Pen_State(char State);
void GoTo(int X, int Y);

void main()
{
	Init5024(2, 0, 0, 0, 0);
	LED_init();
	while(Stand_By == 0)
	{
		Set5050(&Signal[0], _5050_0, 0, ABit);
		Set5050(&Signal[0], _5050_0, 1, ABit);
		Set5050(&Signal[0], _5050_0, 2, ABit);
		Set5050(&Signal[0], _5050_0, 3, ABit);
		Set5050(&Signal[0], _5050_1, 0, ABit);
		Set5050(&Signal[0], _5050_1, 1, ABit);
		Set5050(&Signal[0], _5050_1, 2, ABit);
		Set5050(&Signal[0], _5050_1, 3, ABit);
		Set5050(&Work[0], _5050_0, 4, ABit);
		Get5050(_5050_1, 4, ABit, &Stand_By);
	}

	Pen_State('U');
	GoTo(50, 50);
	prevX = 0;
	prevY = 0;

	

	int cx = 200;
	int cy = 200;
	int r  = 200;

	// Начинаем с правого края
	int startX = cx + r;
	int startY = cy;
	GoTo(startX, startY);

	Pen_State('D');

	// Идём по углу с мелким шагом
	float phi;
	float dphi;
	int px;
	int py;

	dphi = 0.02f;   // ~0.02 рад ≈ 1.15°, примерно 315 точек на круг
	phi = 0.0f;
	while(phi < 6.2832f)
	{
		px = cx + (r * cos(phi));
		py = cy + (r * sin(phi));
		GoTo(px, py);
		phi = phi + dphi;
	}

	// Замыкаем
	GoTo(startX, startY);

	//Поднимаем перо
	Pen_State('U');

	//Обнуляем сигналы
	Set5050(&Signal[0], _5050_0, 0, ABit);
	Set5050(&Signal[0], _5050_0, 1, ABit);
	Set5050(&Signal[0], _5050_0, 2, ABit);
	Set5050(&Signal[0], _5050_0, 3, ABit);
	Set5050(&Signal[0], _5050_1, 0, ABit);
	Set5050(&Signal[0], _5050_1, 1, ABit);
	Set5050(&Signal[0], _5050_1, 2, ABit);
	Set5050(&Signal[0], _5050_1, 3, ABit);
}

void Pen_State(char State)
{
	if(State == 'U')
	{
		Set5050(&Work[0], _5050_0, 4, ABit);
	}
	else if(State == 'D')
	{
		Set5050(&Work[1], _5050_0, 4, ABit);
	}
}

//Линия в точку (X, Y), мм. 4 шага (фазы) на 1 мм, алгоритм Брезенхема.
void GoTo(int X, int Y)
{
	int dx;
	int dy;
	int isRight = 1;
	int isTop = 1;
	int stepsN;
	int errX;
	int errY;
	int cnt;

	dx = X - prevX;
	dy = Y - prevY;

	if(dx < 0)
	{
		isRight = 0;
		dx = -dx;
	}
	if(dy < 0)
	{
		isTop = 0;
		dy = -dy;
	}

	//умножаем на 4 (4 шага на 1 мм)
	dx = dx + dx;
	dx = dx + dx;
	dy = dy + dy;
	dy = dy + dy;

	stepsN = dx;
	if(stepsN < dy)
	{
		stepsN = dy;
	}

	errX = 0;
	errY = 0;
	cnt = 0;
	while(cnt < stepsN)
	{
		errX = errX + dx;
		errY = errY + dy;

		//Шаг по X (мотор 0): errX >= stepsN
		if(stepsN < errX + 1)
		{
			errX = errX - stepsN;
			if(isRight == 1)
			{
				phX = phX + 1;
				if(phX == 4)
				{
					phX = 0;
				}
			}
			else
			{
				if(phX == 0)
				{
					phX = 3;
				}
				else
				{
					phX = phX - 1;
				}
			}

			if(phX == 0)
			{
				Set5050(&Signal[1], _5050_0, 0, ABit);
				Set5050(&Signal[0], _5050_0, 1, ABit);
				Set5050(&Signal[0], _5050_0, 2, ABit);
				Set5050(&Signal[1], _5050_0, 3, ABit);
			}
			else if(phX == 1)
			{
				Set5050(&Signal[1], _5050_0, 0, ABit);
				Set5050(&Signal[1], _5050_0, 1, ABit);
				Set5050(&Signal[0], _5050_0, 2, ABit);
				Set5050(&Signal[0], _5050_0, 3, ABit);
			}
			else if(phX == 2)
			{
				Set5050(&Signal[0], _5050_0, 0, ABit);
				Set5050(&Signal[1], _5050_0, 1, ABit);
				Set5050(&Signal[1], _5050_0, 2, ABit);
				Set5050(&Signal[0], _5050_0, 3, ABit);
			}
			else
			{
				Set5050(&Signal[0], _5050_0, 0, ABit);
				Set5050(&Signal[0], _5050_0, 1, ABit);
				Set5050(&Signal[1], _5050_0, 2, ABit);
				Set5050(&Signal[1], _5050_0, 3, ABit);
			}
			ADAMdelay(10);
		}

		//Шаг по Y (мотор 1): errY >= stepsN
		if(stepsN < errY + 1)
		{
			errY = errY - stepsN;
			if(isTop == 1)
			{
				phY = phY + 1;
				if(phY == 4)
				{
					phY = 0;
				}
			}
			else
			{
				if(phY == 0)
				{
					phY = 3;
				}
				else
				{
					phY = phY - 1;
				}
			}

			if(phY == 0)
			{
				Set5050(&Signal[1], _5050_1, 0, ABit);
				Set5050(&Signal[0], _5050_1, 1, ABit);
				Set5050(&Signal[0], _5050_1, 2, ABit);
				Set5050(&Signal[1], _5050_1, 3, ABit);
			}
			else if(phY == 1)
			{
				Set5050(&Signal[1], _5050_1, 0, ABit);
				Set5050(&Signal[1], _5050_1, 1, ABit);
				Set5050(&Signal[0], _5050_1, 2, ABit);
				Set5050(&Signal[0], _5050_1, 3, ABit);
			}
			else if(phY == 2)
			{
				Set5050(&Signal[0], _5050_1, 0, ABit);
				Set5050(&Signal[1], _5050_1, 1, ABit);
				Set5050(&Signal[1], _5050_1, 2, ABit);
				Set5050(&Signal[0], _5050_1, 3, ABit);
			}
			else
			{
				Set5050(&Signal[0], _5050_1, 0, ABit);
				Set5050(&Signal[0], _5050_1, 1, ABit);
				Set5050(&Signal[1], _5050_1, 2, ABit);
				Set5050(&Signal[1], _5050_1, 3, ABit);
			}
			ADAMdelay(10);
		}

		cnt = cnt + 1;
	}

	prevX = X;
	prevY = Y;
}