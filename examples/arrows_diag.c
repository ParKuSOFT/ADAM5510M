#include "5510drv.h"

//Сигналы на обмотку двигателей
unsigned char Signal[2] = {0, 1};
unsigned char Work[2] = {0, 1};
//Сигнал состояния пера и кнопки Stand_By
unsigned char Stand_By = 0;

//Переменные для номеров слотов
unsigned char _5050_0 = 0;
unsigned char _5050_1 = 1;

//Декларирование функции
void Pen_State(char State);
void GoToLeftOrBottom(int isY);
void GoToRightOrTop(int isY);
void Phs(int isY, int num);
void Diag(int xr, int yr);

void main()
{
	//Переменная для циклов
	int i;

	//Ожидание нажатия кнопки Stand_By
	while(Stand_By == 0)
	{
		//Сигналы на обмотку первого мотора 0 0 0 0
		Set5050(&Signal[0], _5050_0, 0, ABit);
		Set5050(&Signal[0], _5050_0, 1, ABit);
		Set5050(&Signal[0], _5050_0, 2, ABit);
		Set5050(&Signal[0], _5050_0, 3, ABit);
		//Сигналы на обмотку второго мотора 0 0 0 0
		Set5050(&Signal[0], _5050_1, 0, ABit);
		Set5050(&Signal[0], _5050_1, 1, ABit);
		Set5050(&Signal[0], _5050_1, 2, ABit);
		Set5050(&Signal[0], _5050_1, 3, ABit);
		//Поднять перо и проверить Stand_By
		Set5050(&Work[0], _5050_0, 4, ABit);
		Get5050(_5050_1, 4, ABit, &Stand_By);
	}
		//ПОДНИМАЕМ перо----------------------
		Pen_State('U');
		
		//Смещение пера вправо и вверх на 5 см
		for(i = 0; i < 50; i++)
		{
			Diag(1, 1);
		}

		//Опускаем перо----------------------
		Pen_State('D');
		//Рисуем первую 18 см линию вверх
		for (i = 0; i < 180; i++)
		{
			GoToRightOrTop(_5050_1);
		}
		for (i = 0; i < 180; i++)
		{
			GoToRightOrTop(_5050_0);
		}
		//Диагональ вправо-вниз
		for (i = 0; i < 90; i++)
		{
			Diag(1, 0);
		}
		//Диагональ влево-вниз
		for (i = 0; i < 90; i++)
		{
			Diag(0, 0);
		}
		for (i = 0; i < 180; i++)
		{
			GoToLeftOrBottom(_5050_0);
		}

		Pen_State('U');

		//Перемещение вправо-вверх
		for (i = 0; i < 180; i++)
		{
			Diag(1, 1);
		}

		// Вторая стрелка
		Pen_State('D');
		for (i = 0; i < 70; i++)
		{
			GoToRightOrTop(_5050_0);
		}
		for (i = 0; i < 90; i++)
		{
			Diag(1, 0);
		}
		for (i = 0; i < 90; i++)
		{
			Diag(0, 0);
		}
		for (i = 0; i < 70; i++)
		{
			GoToLeftOrBottom(_5050_0);
		}

		Pen_State('U');

		for (i = 0; i < 70; i++)
		{
			GoToRightOrTop(_5050_0);
		}
		for (i = 0; i < 180; i++)
		{
			GoToRightOrTop(_5050_1);
		}

		// Третья
		Pen_State('D');
		for (i = 0; i < 70; i++)
		{
			GoToRightOrTop(_5050_0);
		}
		for (i = 0; i < 90; i++)
		{
			Diag(1, 0);
		}
		for (i = 0; i < 90; i++)
		{
			Diag(0, 0);
		}
		for (i = 0; i < 70; i++)
		{
			GoToLeftOrBottom(_5050_0);
		}

		Pen_State('U');

		//Сигналы на обмотку первого мотора 0 0 0 0
		Set5050(&Signal[0], _5050_0, 0, ABit);
		Set5050(&Signal[0], _5050_0, 1, ABit);
		Set5050(&Signal[0], _5050_0, 2, ABit);
		Set5050(&Signal[0], _5050_0, 3, ABit);
		//Сигналы на обмотку второго мотора 0 0 0 0
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

//Одна фаза обмотки мотора isY: num = 0 (1001), 1 (1100), 2 (0110), 3 (0011)
void Phs(int isY, int num)
{
	if(num == 0)
	{
		//1 0 0 1
		Set5050(&Signal[1], isY, 0, ABit);
		Set5050(&Signal[0], isY, 1, ABit);
		Set5050(&Signal[0], isY, 2, ABit);
		Set5050(&Signal[1], isY, 3, ABit);
	}
	else if(num == 1)
	{
		//1 1 0 0
		Set5050(&Signal[1], isY, 0, ABit);
		Set5050(&Signal[1], isY, 1, ABit);
		Set5050(&Signal[0], isY, 2, ABit);
		Set5050(&Signal[0], isY, 3, ABit);
	}
	else if(num == 2)
	{
		//0 1 1 0
		Set5050(&Signal[0], isY, 0, ABit);
		Set5050(&Signal[1], isY, 1, ABit);
		Set5050(&Signal[1], isY, 2, ABit);
		Set5050(&Signal[0], isY, 3, ABit);
	}
	else
	{
		//0 0 1 1
		Set5050(&Signal[0], isY, 0, ABit);
		Set5050(&Signal[0], isY, 1, ABit);
		Set5050(&Signal[1], isY, 2, ABit);
		Set5050(&Signal[1], isY, 3, ABit);
	}
	ADAMdelay(10);
}

//Диагональ на 1 мм под 45 градусов: фазы X и Y чередуются.
//xr = 1 вправо, 0 влево; yr = 1 вверх, 0 вниз.
//Порядок фаз у каждого мотора тот же, что в GoToRightOrTop и GoToLeftOrBottom:
//вправо/вверх 0,1,2,3; влево/вниз 0,3,2,1.
void Diag(int xr, int yr)
{
	Phs(_5050_0, 0);
	Phs(_5050_1, 0);

	if(xr == 1)
	{
		Phs(_5050_0, 1);
	}
	else
	{
		Phs(_5050_0, 3);
	}
	if(yr == 1)
	{
		Phs(_5050_1, 1);
	}
	else
	{
		Phs(_5050_1, 3);
	}

	Phs(_5050_0, 2);
	Phs(_5050_1, 2);

	if(xr == 1)
	{
		Phs(_5050_0, 3);
	}
	else
	{
		Phs(_5050_0, 1);
	}
	if(yr == 1)
	{
		Phs(_5050_1, 3);
	}
	else
	{
		Phs(_5050_1, 1);
	}
}

void GoToLeftOrBottom(int isY)
{
	//идём влево/вниз
	//Сигналы на обмотку 1 0 0 1
		Set5050(&Signal[1], isY, 0, ABit);
		Set5050(&Signal[0], isY, 1, ABit);
		Set5050(&Signal[0], isY, 2, ABit);
		Set5050(&Signal[1], isY, 3, ABit);
		ADAMdelay(10);
	//Сигналы на обмотку 0 0 1 1
		Set5050(&Signal[0], isY, 0, ABit);
		Set5050(&Signal[0], isY, 1, ABit);
		Set5050(&Signal[1], isY, 2, ABit);
		Set5050(&Signal[1], isY, 3, ABit);
		ADAMdelay(10);
		//Сигналы на обмотку 0 1 1 0
		Set5050(&Signal[0], isY, 0, ABit);
		Set5050(&Signal[1], isY, 1, ABit);
		Set5050(&Signal[1], isY, 2, ABit);
		Set5050(&Signal[0], isY, 3, ABit);
		ADAMdelay(10);
		//Сигналы на обмотку 1 1 0 0
		Set5050(&Signal[1], isY, 0, ABit);
		Set5050(&Signal[1], isY, 1, ABit);
		Set5050(&Signal[0], isY, 2, ABit);
		Set5050(&Signal[0], isY, 3, ABit);
		ADAMdelay(10);
}

void GoToRightOrTop(int isY)
{
	//идём вправо/вверх
		//Сигналы на обмотку 1 0 0 1
		Set5050(&Signal[1], isY, 0, ABit);
		Set5050(&Signal[0], isY, 1, ABit);
		Set5050(&Signal[0], isY, 2, ABit);
		Set5050(&Signal[1], isY, 3, ABit);
		ADAMdelay(10);
		//Сигналы на обмотку 1 1 0 0
		Set5050(&Signal[1], isY, 0, ABit);
		Set5050(&Signal[1], isY, 1, ABit);
		Set5050(&Signal[0], isY, 2, ABit);
		Set5050(&Signal[0], isY, 3, ABit);
		ADAMdelay(10);
		//Сигналы на обмотку 0 1 1 0
		Set5050(&Signal[0], isY, 0, ABit);
		Set5050(&Signal[1], isY, 1, ABit);
		Set5050(&Signal[1], isY, 2, ABit);
		Set5050(&Signal[0], isY, 3, ABit);
		ADAMdelay(10);
		//Сигналы на обмотку 0 0 1 1
		Set5050(&Signal[0], isY, 0, ABit);
		Set5050(&Signal[0], isY, 1, ABit);
		Set5050(&Signal[1], isY, 2, ABit);
		Set5050(&Signal[1], isY, 3, ABit);
		ADAMdelay(10);
}
