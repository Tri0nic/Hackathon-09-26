FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src
COPY FireRisk.Api/FireRisk.Api.csproj FireRisk.Api/
RUN dotnet restore FireRisk.Api/FireRisk.Api.csproj
COPY FireRisk.Api/ FireRisk.Api/
RUN dotnet publish FireRisk.Api/FireRisk.Api.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app
COPY --from=build /app .
EXPOSE 8080
ENTRYPOINT ["dotnet", "FireRisk.Api.dll"]
