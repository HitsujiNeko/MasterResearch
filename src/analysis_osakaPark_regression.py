import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import statsmodels.api as sm

# データ読み込み
csv_path = r"data/input/osaka_park_LST/osakaPark.csv"
df = pd.read_csv(csv_path)

# 散布図
plt.figure(figsize=(8,6))
sns.scatterplot(x='log10_area', y='dif_LST', data=df)
plt.xlabel('log10_area')
plt.ylabel('delta_LST')
plt.title('green area vs delta LST')
plt.tight_layout()
plt.show()

# 線形回帰分析
X = df['log10_area']
Y = df['dif_LST']
X = sm.add_constant(X)  # 切片追加
model = sm.OLS(Y, X).fit()
print(model.summary())

# 回帰直線の可視化
plt.figure(figsize=(8,6))
sns.scatterplot(x='log10_area', y='dif_LST', data=df, label='Data points')
plt.plot(df['log10_area'], model.predict(X), color='red', label='Regression line')
plt.xlabel('log10_area')
plt.ylabel('delta_LST')
plt.title('green area vs delta LST')
plt.legend()
plt.tight_layout()
plt.show()
