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

	//Ожидание нажатия кнопки Stand_By
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

	//Опускаем перо и рисуем тестовый квадрат 1 см
	Pen_State('D');
	GoTo(10, 0);
	GoTo(10, 10);
	GoTo(0, 10);
	GoTo(0, 0);
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
//В условиях только простые сравнения, без сложных выражений.
void GoTo(int X, int Y)
{
	int dx;
	int dy;
	int isRight = 1;
	int isTop = 1;
	int stepsN;
	int errX;
	int errY;
	int cmpX;
	int cmpY;
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

		//Шаг по X (мотор 0), если errX >= stepsN
		cmpX = errX + 1;
		if(stepsN < cmpX)
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
				//1 0 0 1
				Set5050(&Signal[1], _5050_0, 0, ABit);
				Set5050(&Signal[0], _5050_0, 1, ABit);
				Set5050(&Signal[0], _5050_0, 2, ABit);
				Set5050(&Signal[1], _5050_0, 3, ABit);
			}
			else if(phX == 1)
			{
				//1 1 0 0
				Set5050(&Signal[1], _5050_0, 0, ABit);
				Set5050(&Signal[1], _5050_0, 1, ABit);
				Set5050(&Signal[0], _5050_0, 2, ABit);
				Set5050(&Signal[0], _5050_0, 3, ABit);
			}
			else if(phX == 2)
			{
				//0 1 1 0
				Set5050(&Signal[0], _5050_0, 0, ABit);
				Set5050(&Signal[1], _5050_0, 1, ABit);
				Set5050(&Signal[1], _5050_0, 2, ABit);
				Set5050(&Signal[0], _5050_0, 3, ABit);
			}
			else
			{
				//0 0 1 1
				Set5050(&Signal[0], _5050_0, 0, ABit);
				Set5050(&Signal[0], _5050_0, 1, ABit);
				Set5050(&Signal[1], _5050_0, 2, ABit);
				Set5050(&Signal[1], _5050_0, 3, ABit);
			}
			ADAMdelay(10);
		}

		//Шаг по Y (мотор 1), если errY >= stepsN
		cmpY = errY + 1;
		if(stepsN < cmpY)
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
				//1 0 0 1
				Set5050(&Signal[1], _5050_1, 0, ABit);
				Set5050(&Signal[0], _5050_1, 1, ABit);
				Set5050(&Signal[0], _5050_1, 2, ABit);
				Set5050(&Signal[1], _5050_1, 3, ABit);
			}
			else if(phY == 1)
			{
				//1 1 0 0
				Set5050(&Signal[1], _5050_1, 0, ABit);
				Set5050(&Signal[1], _5050_1, 1, ABit);
				Set5050(&Signal[0], _5050_1, 2, ABit);
				Set5050(&Signal[0], _5050_1, 3, ABit);
			}
			else if(phY == 2)
			{
				//0 1 1 0
				Set5050(&Signal[0], _5050_1, 0, ABit);
				Set5050(&Signal[1], _5050_1, 1, ABit);
				Set5050(&Signal[1], _5050_1, 2, ABit);
				Set5050(&Signal[0], _5050_1, 3, ABit);
			}
			else
			{
				//0 0 1 1
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
