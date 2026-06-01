      Program Horizon2000
c
c     Appendix
c     SHIONO, K., NOUMI, Y., MASUMOTO, S. and SAKAMOTO, M. (2001)
c     Horizon2000 : Revised Fortran Program for Optimal Determination of 
c     Geological Surfaces Based on Field Observation Including Equality-
c     Inequality Constraints and Slope Information. 
c     Geoinformatics, vol.12, no.4, pp229-249.
c
c     Fortran77 program for determination of an optimal geologic surface
c     using both coordinates of outcrops and inclination data.
c     Revised from N88-BASIC program shown in :
c     SHIONO,K., WADATSUMI,K. and MASUMOTO,S.(1987):Numerical Determination
c        of the Optimal Geological Surface - A New Gridding Algorithm for
c        Geological Data Including Inequality and Dip Information -.
c        Joho chishitsu (Geological Data Processing), no.12, pp.299-328.
c
c     Basic concepts
c     (1) A surface f(x,y) is approximated by a set of values f(i,j)
c         at grid points (xg(i),yg(j)).  i = 1 to Nx, j = 1 to Ny.
c     (2) Location of outcrop (xh(k),yh(k),zh(k)) provides equality and
c         inequaloty constraints to the surface:
c            f(xh(k),yh(k)) = zh(k)  if lm(k) = 0
c            f(xh(k),yh(k)) < zh(k)  if lm(k) < 0
c            f(xh(k),yh(k)) > zh(k)  if lm(k) > 0.
c         f(x,y) is approximated by quadratic interpolation
c         using 6 values at neighbouring grid points
c     (3) Slope observation also provides constrains to df/dx and df/dy :
c            fx(xd(k),yd(k)) + sin(tr(k))*tan(dp(k)) = 0
c            fy(xd(k),yd(k)) + cos(tr(k))*tan(dp(k)) = 0
c         where tr(k) : azimuth of max. slope, dp(k) : dip angle
c         it is assumed that df/dx and df/dy are constant in the vertical.
c     (4) Surface determination is equivalent to
c         a constrained optimization problem :
c            Find the optimal solution f(x,y) such that
c            objective function J(smoothness of the surface)
c              = m1*[double integral: (fx)**2 + (fy)**2 dxdy]
c               +m2*[double integral: (fxx)**2+2(fxy)**2+(fyy)**2 dxdy]
c            becomes minimum
c            subject to
c               f(xh(k),yh(k)) = zh(k)  if lm(k) = 0
c               f(xh(k),yh(k)) < zh(k)  if lm(k) < 0
c               f(xh(k),yh(k)) > zh(k)  if lm(k) > 0
c            and 
c               fx(xd(k),yd(k)) + sin(tr(k))*tan(dp(k)) = 0
c               fy(xd(k),yd(k)) + cos(tr(k))*tan(dp(k)) = 0.
c     (5) The optimization problem is solved by the penalty method :
c             Q(f;a)=J(smoothness)+ a*R(mean of squared residuals) ---> min
c         where a is a constant called a penalty.
c         The optimal surface is a solution of linear simultaneous equations :
c             A u = b        defined by dQ/df(i,j) = 0.
c     (6) The simultaneous equations is solved by Choleski's method.
c
c Input data  
c     (a) xh(k), yh(k), zh(k), lm(k)          k=1 to NH
c         location of outcrop : xh(k), yh(k), zh(k)
c         relation to surface : lm(k) =  0 ; surface must pass the point
c                                     = -1 ; suface must pass under the point
c                                     =  1 ; surface must pass above the point
c     (b) xd(k), yd(k), zd(k), tr(k), dp(k)    k=1 to ND
c         location of outcrop : xd(k),yd(k),zd(k)
c         trend & dip in deg  : tr(k),dp(k)
c
c Output : grid data
c      number of grid   : Nx, Ny
c      origin of grid   : (xmin,ymin)
c      interval of grid : dx,dy
c      grid point       : (xg(i), yg(j))
c      elevation        : f(i,j)        i = 1 to Nx, j = 1 to Ny
c
c     Note the limitation of array dimension:
c        mxdt           = 1000000 : maximum number of observation data
c        ngrid          =  201    : maximun number of grid (Nx and Ny)
c        mxdim=ngrid**2 =40401    : maximun number of grid points (Nx*Ny)
c        mxgrd=2*ngrid+3=  405    : maximum number of half band width
c     Number of grid points must be smaller than ngrid x ngrid.
c 
      parameter (mxdt=1000000,ngrid=201,mxdim=40401,mxgrd=405)
      implicit real*8 (a-h,o-z)
      character*80 nfg
      dimension xh(mxdt),yh(mxdt),zh(mxdt),lm(mxdt)
      dimension xd(mxdt),yd(mxdt),zd(mxdt),dfdx(mxdt),dfdy(mxdt)
      dimension tr(mxdt),dp(mxdt)
      dimension xg(ngrid),yg(ngrid),f(ngrid,ngrid)
      dimension A(mxdim,mxgrd),b(mxdim)
c
c [step 1]----------observation data----------------------------------
c
c                             list of elevation data
c                             id,   x,   y,   z,  l
c                              0, 9e9, 9e9, 9e9, 99  <- end of file
c
 1000 write (*,*) 'input elevation data from file'
      call xyzdt(xh,yh,zh,lm,mxdt,nh,xl,xr,yl,yr,zl,zr)
         if (nh .lt. 1) then
            write (*,*) ' error --- no elevation data in file'
            goto 9000
         end if
c
c                             list of slope data
c                             id,   x,   y,   z, trend, dip
c                              0, 9e9, 9e9, 9e9,   9e9, 9e9 <- end of file
c
      write (*,10)
   10 format (' Do you have data on slope ?'/
     &        '   1(yes) / 0(no) : ', $)
      read (*,*) idata
         if (idata .ne. 1) then
            nd = 0
            goto 2000
         end if
      write (*,*) 'input data on slope from file'
      call dipdt(xd,yd,zd,dfdx,dfdy,tr,dp,mxdt,nd,xl,xr,yl,yr)
         if (nd.lt.1) then
            write (*,*) ' error --- no slope data in file'
            go to 9000
         end if
c
c [step 2]----------assign grid geometry------------------------------
c
 2000 write (*,20) xl,xr,yl,yr,zl,zr,nh,nd
      write (*,22)
   20 format (' observed data'/
     &        ' area   : x(min),x(max) = ',2f12.4/
     &        '        : y(min),y(max) = ',2f12.4/
     &        '        : z(min),z(max) = ',2f12.4/
     &        ' number : NH(elevation) = ',i7/
     &        '        : ND(slope)     = ',i7)
   22 format ('-----assign grid geometry------------',/
     &        ' area   : x(min),x(max) = ', $)
      read (*,*) xming,xmaxg
         if (xmaxg .le. xming) goto 9000
      write (*,24)
   24 format ('        : y(min),y(max) = ', $)
      read (*,*) yming,ymaxg
         if (ymaxg .le. yming) goto 9000
      write (*,26) ngrid
   26 format (' grid number Nx & Ny must be =< ',i4/
     &        '        : Nx,  Ny       = ', $)
      read (*,*) nxg,nyg
         if ( (nxg.lt.2)     .or. (nyg.lt.2)     ) goto 9000
         if ( (nxg.gt.mxgrd) .or. (nyg.gt.mxgrd) ) goto 9000
         dx = (xmaxg - xming) / dfloat(nxg - 1)
         dy = (ymaxg - yming) / dfloat(nyg - 1)
c
c [step 3]----------expand calculation area---------------------------
c
 3000 write (*,30)
   30 format (' expand area  from 0%(original) to 50% in length'/
     &        '       xexp(%), yexp(%) = ', $)
      read (*,*) xexp,yexp
c
         nxe = idint( dfloat(nxg-1)*xexp/100.0 + 0.50000001 )
         if (nxe .lt. 1) nxe = 1
         Nx  = nxg + 2 * nxe
         if (Nx .gt. mxgrd) then
            write (*,32) Nx,mxgrd
   32       format ('  n =',i6,'  too large! Must be less than',i6)
            goto 3000
         end if
         xmin = xming - dfloat(nxe) * dx
         do 310 i=1,Nx
            xg(i) = xmin + dfloat(i-1) * dx
  310    continue
c
         nye = idint( dfloat(nyg-1)*yexp/100.0 + 0.50000001 )
         if (nye .lt. 1) nye = 1
         ny = nyg + 2 * nye
         if (Ny .gt. mxgrd) then
            write (*,32) Ny,mxgrd
            goto 3000
         end if
         ymin = yming - dfloat(nye) * dy
         do 320 j=1,Ny
            yg(j) = ymin + dfloat(j-1) * dy
  320    continue
c
c [step 4]----------calculation of the optimal surface----------------
c
c                         initialize f(i,j)
 4000 do 400 i=1,Nx
      do 400 j=1,Ny
         f(i,j) = (zr + zl) / 2.0
  400 continue
c                                                optimal surface
 4100 call optimals(f,ngrid,Nx,Ny,xmin,ymin,dx,dy,xh,yh,zh,lm,
     &   mxdt,nh,nhdt,xd,yd,dfdx,dfdy,nd,nddt,alpha,beta,
     &   pm1,pm2,A,b,mxdim,mxgrd,nmat,nband,iflg)
         if (iflg .ne. 0) goto 9000
c
c [step 5]----------output of result to file--------------------------
c
 5000 write (*,50) 
   50 format (' output of result to file'/
     &        ' file name (grid data) or no (skip) :', $)
      read (*,52) nfg
   52 format (a80)
      if ( (nfg.eq.'NO') .or. (nfg.eq.'no') ) goto 9000
c
      lu = 62
      open (lu,file=nfg,err=9000)
      write (lu,*) nxg,nyg,xming,yming,dx,dy
      do 500 i=1,nxg
         write (lu,*) (f(i+nxe,j+nye),j=1,nyg)
  500 continue
      close(lu)
c
c [step 6]----------next work-----------------------------------------
c
 9000 write (*,*) ' ------------next work---------------'
      write (*,*) '  read next data             = 1'
      write (*,*) '  change grid                = 2'
      write (*,*) '  change expand area         = 3'
      write (*,*) '  set parameter(reset   fij) = 4'
      write (*,*) '               (present fij) = 5'
      write (*,*) '  output to file             = 6'
      write (*,*) '  end                        = others'
      write (*,90)
   90 format ('            work number = ', $)
      read (*,*) nwork
      goto (1000,2000,3000,4000,4100,5000) nwork
      stop
      end
c
c----------------------subroutine xyzdt-------------------------------
c     input elevation data: id,xh(k),yh(k),zh(k),lm(k)   k=1 to nh
c---------------------------------------------------------------------
      subroutine xyzdt(xh,yh,zh,lm,mxdt,nh,xl,xr,yl,yr,zl,zr)
c
      implicit real*8 (a-h,o-z)
      character*80 nfh
      dimension xh(mxdt),yh(mxdt),zh(mxdt),lm(mxdt)
c
      write (*,10)
   10 format ('        file name = ', $)
      read (*,12) nfh
   12 format (a80)
c
      lu = 52
      open (lu,file=nfh,err=900)
      read (lu,*,end=110) id,xh(1),yh(1),zh(1),lm(1)
         xl = xh(1) 
         xr = xh(1)
         yl = yh(1)
         yr = yh(1)
         zl = zh(1)
         zr = zh(1)
         do 100 k=2,mxdt
            read (lu,*,end=110) id,xh(k),yh(k),zh(k),lm(k)
            if (abs(xh(k)) .gt. 1.0e+09) goto 110
               if (xh(k) .gt. xr) xr = xh(k)
               if (xh(k) .lt. xl) xl = xh(k)
               if (yh(k) .gt. yr) yr = yh(k)
               if (yh(k) .lt. yl) yl = yh(k)
               if (zh(k) .gt. zr) zr = zh(k)
               if (zh(k) .lt. zl) zl = zh(k)
  100    continue
  110    nh = k - 1
         write (*,14) nh
   14    format (' number of elevation data : NH = ',i7)
      close(lu)
      return
c
  900 write (*,90) nfh
   90 format (' error at open file ',a80)
      nh = 0
      return
      end
c
c----------------------subroutine dipdt--------------------------------------
c     input trend of max. sloep & dip angle: id,xd(k),yd(k),zd(k),tr(k),dp(k)
c                                            k=1 to nd
c----------------------------------------------------------------------------
      subroutine dipdt(xd,yd,zd,dfdx,dfdy,tr,dp,mxdt,nd,xl,xr,yl,yr)
c
      implicit real*8 (a-h,o-z)
      character*80 nfd
      dimension xd(mxdt),yd(mxdt),zd(mxdt),dfdx(mxdt),dfdy(mxdt)
      dimension tr(mxdt),dp(mxdt)

      pi = 3.14159265358979/180.0
c
      write (*,10)
   10 format ('       file name = ', $)
      read (*,12) nfd
   12 format (a80)
c
      lu = 52
      open (lu,file=nfd,err=900)
      do 100 k=1,mxdt
         read (lu,*,end=110) id,xd(k),yd(k),zd(k),tr(k),dp(k)
            if (abs(xd(k)) .gt. 1.0e+09) goto 110
            if (xd(k) .gt. xr) xr = xd(k)
            if (xd(k) .lt. xl) xl = xd(k)
            if (yd(k) .gt. yr) yr = yd(k)
            if (yd(k) .lt. yl) yl = yd(k)
c                    tr : trend of maximum slope clockwise from N
c                    dp : dip angle from horizontal surface
c                    dfdx(k) = df/dx & dfdy(k) = df/dy
         dfdx(k) = - dsin(pi*tr(k)) * dtan(pi*dp(k))
         dfdy(k) = - dcos(pi*tr(k)) * dtan(pi*dp(k))
  100 continue
  110 nd = k - 1
      write (*,14) nd
   14 format (' number of slope data : ND = ',i5)
      close(lu)
      return
c
  900 write (*,90) nfd
   90 format (' error at open file ',a80)
      nd = 0
      return
      end
c
c----------------------subroutine optimals----------------------------
c     Optimal surface determination by outerior penalty method
c         Q(f;a)=J(smoothness)+ a*R(residual) ---> min
c     return with
c       iflg= 0 : determination of surface f(i,j)
c       iflg= 1 : error at matrix setting         (insufficient data)
c       iflg= 2 : error at simultaneous equations (A : singular matrix)
c       iflg= 3 : return without calculation
c----------------------------------------------------------------------
      subroutine optimals(f,ngrid,Nx,Ny,xmin,ymin,dx,dy,xh,yh,zh,lm,
     &          mxdt,nh,nhdt,xd,yd,dfdx,dfdy,nd,nddt,alpha,beta,
     &          pm1,pm2,A,b,mxdim,mxgrd,nmat,nband,iflg)
c
      implicit real*8 (a-h,o-z)
      dimension f(ngrid,ngrid)
      dimension xh(mxdt),yh(mxdt),zh(mxdt),lm(mxdt)
      dimension xd(mxdt),yd(mxdt),dfdx(mxdt),dfdy(mxdt)
      dimension A(mxdim,mxgrd),b(mxdim)
c
      nmat  = Nx * Ny
      nband = 2 * Ny + 2
      mm    = nmat
      iflg = 3
c                               (1) parameters : pm1, pm2
      write (*,10)
   10 format (' ----------parameters---------------------'/
     &        '  J = m1*[(fx)**2+(fy)**2]+'/
     &        '      m2*[(fxx)**2+2(fxy)**2+(fyy)**2]'/
     &        '                  : m1  = ', $)
      read (*,*) pm1
         if (pm1 .lt. 0.0) goto 900
      write (*,12)
   12 format ('                  : m2  = ', $)
      read (*,*) pm2
         if (pm2 .lt. 0.0) goto 900
c
c                                 (2) penalty : alpha for elevation data
      itry = 0
      do 200 k=1,nh
         itry = itry + lm(k)**2
  200 continue
      if (itry .gt. 0) goto 210
c                                  no iteration
      write (*,20)
   20 format (' no iteration is requied'/
     &        '      penalty :  alpha  = ', $)
      read (*,*) alphamin
         if (alphamin .le. 0.0) goto 900
         alphamax = alphamin
         ratio    = 1.0
         nitr     = 1
         goto 300
c                                   iteration
  210 write (*,22)
   22 format (' some iteration is required'/
     &        '  penalty : alpha (min)  = ', $)
      read (*,*) alphamin
         if (alphamin .le. 0.0) goto 900
      write (*,24)
   24 format ('          : alpha (max)  = ', $)
      read (*,*) alphamax
         if (alphamax .le. 0.0     ) goto 900
         if (alphamax .lt. alphamin) goto 900
      write (*,26)
   26 format ('    number of iteration  = ', $)
      read (*,*) nitr
         if (nitr .le. 1) goto 900
      rn = 1.0/dfloat(nitr - 1)
      ratio = (alphamax/alphamin)**rn
c
c                                 (3) penalty : beta for slope data
  300 if (nd .eq. 0) then
         gamma = 0.0
      else
         write (*,30)
   30    format ('   gamma   (beta/alpha) = ', $)
         read (*,*) gamma
         if (gamma. lt. 0.0) goto 900
      end if
c
c                                 (4) iterative calculation
      do 400 itr=1,nitr
         alpha = alphamin * (ratio**dfloat(itr-1))
         beta  = alpha*gamma
         write (*,40) itr,alpha
   40    format (' iteration =',i4,'  penalty =',E12.5)
c                                (a) set matrix
         call setmat(A,b,mxdim,mxgrd,nmat,nband,f,ngrid,Nx,Ny,
     &        xmin,ymin,dx,dy,pm1,pm2,alpha,beta,xh,yh,zh,lm,
     &        mxdt,nh,nhdt,xd,yd,dfdx,dfdy,nd,nddt,iflg)
           if (iflg .eq. 1) goto 900
c                                (b) solve equation A u = b
         call bcholeski(A,b,mxdim,mxgrd,nband,mm,iflg)
           if (iflg .eq. 2) goto 900
c                                (c) solution f(i,j)
         do 410 i=1,Nx
         do 410 j=1,Ny
            igmt   = Ny * (i-1) + j
            f(i,j) = b(igmt)
  410    continue
c
      call Jvalue(f,ngrid,Nx,Ny,dx,dy,Qj1,Qj2)
      write (*,42) Qj1,Qj2
   42 format (/' J1 =',E12.5,'     J2 =',E12.5)
c
      call Rhvalue(f,ngrid,Nx,Ny,dx,dy,xmin,ymin,
     &             xh,yh,zh,lm,mxdt,nh,nhdt,Qhres)
      Qhrn = Qhres/dfloat(nhdt)
      Qhav = dsqrt(Qhrn)
      write (*,44) nhdt,Qhrn,Qhav
   44 format ('  H : data =',i7,'   RH =',E12.5,'  Error =',E12.5)
c
      Qdrn = 0.0
      if (nd .eq. 0) goto 420
      call Rdvalue(f,ngrid,Nx,Ny,dx,dy,xmin,ymin,
     &             xd,yd,dfdx,dfdy,mxdt,nd,nddt,Qdres)
      if (nddt .eq. 0) goto 420
         Qdrn = Qdres/dfloat(nddt)
         Qdav = dsqrt(Qdrn)
         write (*,46) nddt,Qdrn,Qdav
   46    format ('  D : data =',i7,'   RD =',E12.5,'  Error =',E12.5/)
c
  420 Qj  = pm1*Qj1 + pm2*Qj2
      res = alpha*Qhrn + beta*Qdrn
      write (*,48) Qj+res,Qj,res
   48 format ('  Q =',E12.5,'      J =',E12.5,'    a R =',E12.5/)
  400 continue
      iflg = 0
      return
c
  900 write (*,90) iflg
   90 format ('   error  iflg =',i3/
     &  ' iflg= 1 : error at matrix setting (insufficient data)'/
     &  ' iflg= 2 : error at simultaneous equations (singular)'/
     &  ' iflg= 3 : return without calculation')
      return
      end
c
c----------------------subroutine setmat------------------------------
c            constracts linear simultaneous equations  A u = b
c                 A : band matrix     A(i,j) = (i, (i-1)*Ny+j) element 
c                 b : constant vector (Nx*Ny elements)
c---------------------------------------------------------------------
       subroutine setmat(A,b,mxdim,mxgrd,nmat,nband,f,ngrid,
     &     Nx,Ny,xmin,ymin,dx,dy,pm1,pm2,alpha,beta,
     &     xh,yh,zh,lm,mxdt,nh,nhdt,xd,yd,dfdx,dfdy,nd,nddt,iflg)
c
      implicit real*8 (a-h,o-z)
      dimension A(mxdim,mxgrd),b(mxdim)
      dimension f(ngrid,ngrid)
      dimension xh(mxdt),yh(mxdt),zh(mxdt),lm(mxdt)
      dimension xd(mxdt),yd(mxdt),dfdx(mxdt),dfdy(mxdt)
c
c                                  initialize  A(i,j) & b(i)
      iflg = 1
      do 100 i=1,nmat
            b(i)   = 0.0
         do 110 j=1,nband+1
            A(i,j) = 0.0
  110    continue
  100 continue
c
c        pm1*J1 = pm1 * double integral of (fx)**2+(fy)**2
c
      if (pm1. eq. 0.0) goto 200
      call Jx(A,b,mxdim,mxgrd,Nx,Ny,dx,dy,pm1)
      call Jy(A,b,mxdim,mxgrd,Nx,Ny,dx,dy,pm1)
c
c        pm2*J2 = pm2 * double integral of (fxx)**2+2(fxy)**2+(fyy)**2
c
  200 if (pm2. eq. 0.0) go to 300
      call Jxx(A,b,mxdim,mxgrd,Nx,Ny,dx,dy,pm2)
      call Jxy(A,b,mxdim,mxgrd,Nx,Ny,dx,dy,pm2)
      call Jyy(A,b,mxdim,mxgrd,Nx,Ny,dx,dy,pm2)
c
c       alpha*Rh = alpha * sum of (f(xh(k),yh(k)) - zh(k))**2
c
  300 call hmat(A,b,mxdim,mxgrd,f,ngrid,Nx,Ny,xmin,ymin,
     &          dx,dy,xh,yh,zh,lm,mxdt,nh,nhdt,alpha)
c
c       beta*Rd = beta * sum of (fx(xh(k),yh(k)) - dfdx(k))**2
c                             + (fy(xh(k),yh(k)) - dfdy(k))**2
c
      call dmat(A,b,mxdim,mxgrd,Nx,Ny,xmin,ymin,dx,dy,
     &          xd,yd,dfdx,dfdy,mxdt,nd,nddt,beta)
c
      write (*,90) nhdt,nddt
   90 format (' number of elevation constrains : NH =',i7/
     &        ' number of slope constraints    : ND =',i7)
         if (nhdt .lt. 1) return
         if ( (nhdt+2*nddt) .lt. 3) return
      iflg=0
      return
      end
c
c----------------------subroutine Jx ---------------------------------
c      composition of partial block matrix for m1*[(df/dx)**2]
c      partial derivative at ((x(i+1)+x(i))/2,y(j)) is given by
c              df/dx = (f(i+1,j)-f(i,j))/dx
c      double integral is evaluated in a form :
c            1/2  1/2  - -   1/2  1/2      j=Ny
c             1    1   - -    1    1
c             -   -    - -    -    -              *(1/area)
c             1    1   - -    1    1       j=2
c            1/2  1/2        1/2  1/2      j=1
c            i=1  i=2            i=Nx-1
c--------------------------------------------------------------------
      subroutine Jx(A,b,mxdim,mxgrd,Nx,Ny,dx,dy,pm1)
c
      implicit real*8 (a-h,o-z)
      dimension A(mxdim,mxgrd),b(mxdim)
      dimension c(3,3)
c
      call cnull(c)
      c(2,2) = - 1.0/dx
      c(3,2) =   1.0/dx
      wmxy   = pm1 /( dfloat(Nx-1) * dfloat(Ny-1) )
      v = 0.0
      do 100 j=1,Ny
         wy = 1.0
         if ( (j.eq.1) .or. (j.eq.Ny) ) wy = 0.5
         wt = wmxy * wy
      do 100 i=1,Nx-1
         call block9(A,b,mxdim,mxgrd,i,j,Nx,Ny,wt,c,v)
  100 continue
      return
      end
c
c----------------------subroutine Jy ---------------------------------
c      composition of partial block matrix for m1*[(df/dy)**2]
c      partial derivative at (xg(i),(yg(j+1)+yg(j))/2) 
c              df/dy = (f(i,j+1)-f(i,j))/dy
c      double integral is evaluated in a form :
c            1/2   1   - -    1   1/2      j=Ny-1
c            1/2   1   - -    1   1/2
c             -   -    - -    -    -              *(1/area)
c            1/2   1   - -    1   1/2      j=2
c            1/2   1          1   1/2      j=1
c            i=1  i=2             i=Nx
c---------------------------------------------------------------------
      subroutine Jy(A,b,mxdim,mxgrd,Nx,Ny,dx,dy,pm1)
c
      implicit real*8 (a-h,o-z)
      dimension A(mxdim,mxgrd),b(mxdim)
      dimension c(3,3)
c
      call cnull(c)
      c(2,2) = -1.0/dy
      c(2,3) =  1.0/dy
      wmxy = pm1 / ( dfloat(Nx-1) * dfloat(Ny-1) )
      v = 0.0
      do 100 i=1,Nx
         wx = 1.0
         if ( (i.eq.1) .or. (i.eq.Nx) ) wx = 0.5
         wt = wmxy * wx
         do 100 j=1,Ny-1
            call block9(A,b,mxdim,mxgrd,i,j,Nx,Ny,wt,c,v)
  100 continue
      return
      end
c
c----------------------subroutine Jxx---------------------------------
c      composition of partial block matrix for m2*[(ddf/dxdx)**2]
c      partial derivative at (xg(i),yg(j)) is given by
c              ddf/dxdx = (f(i+1,j)-2f(i,j)+f(i-1,j))/dx**2
c      double integral is evaluated in a form (trapezoidal rule):
c            1/4  1/2  - -   1/2  1/4      j=Ny
c            1/2   1   - -    1   1/2
c             -   -    - -    -    -
c            1/2   1   - -    1   1/2      j=2
c            1/4  1/2        1/2  1/4      j=1
c            i=1  i=2             i=Nx
c---------------------------------------------------------------------
      subroutine Jxx(A,b,mxdim,mxgrd,Nx,Ny,dx,dy,pm2)
c
      implicit real*8 (a-h,o-z)
      dimension A(mxdim,mxgrd),b(mxdim)
      dimension c(3,3)
c
      call cnull(c)
      c(1,2) =  1.0 / dx**2.0
      c(2,2) = -2.0 / dx**2.0
      c(3,2) =  1.0 / dx**2.0
      wmxy   =  pm2 * dx * dy
      v = 0.0
      do 100 j=1,Ny
         wy = 1.0
         if ( (j.eq.1) .or. (j.eq.Ny) ) wy = 0.5
      do 100 i=2,Nx-1
         wx = 1.0
            if ( (i.eq.2) .or. (i.eq.Nx-1) ) wx = 1.5
         wt = wmxy * wx * wy
         call block9(A,b,mxdim,mxgrd,i,j,Nx,Ny,wt,c,v)
  100 continue
      return
      end
c
c----------------------subroutine Jyy---------------------------------
c      composition of partial block matrix for m2*[(ddf/dydy)**2]
c      partial derivative at (xg(i),yg(j)) is given by
c              ddf/dydy = (f(i,j+1)-2f(i,j)+f(i,j-1))/dy**2
c      double integral is evaluated in a form (trapezoidal rule):
c            1/4  1/2  - -   1/2  1/4      j=Ny
c            1/2   1   - -    1   1/2
c             -   -    - -    -    -
c            1/2   1   - -    1   1/2      j=2
c            1/4  1/2        1/2  1/4      j=1
c            i=1  i=2             i=Nx
c---------------------------------------------------------------------
      subroutine Jyy(A,b,mxdim,mxgrd,Nx,Ny,dx,dy,pm2)
c
      implicit real*8 (a-h,o-z)
      dimension A(mxdim,mxgrd),b(mxdim)
      dimension c(3,3)
c
      call cnull(c)
      c(2,1) =  1.0/dy**2.0
      c(2,2) = -2.0/dy**2.0
      c(2,3) =  1.0/dy**2.0
      wmxy   =  pm2 * dx * dy
      v = 0.0
      do 100 i=1,Nx
         wx = 1.0
         if ( (i.eq.1) .or. (i.eq.Nx) ) wx = 0.5
      do 100 j=2,Ny-1
         wy = 1.0
         if ( (j.eq.2) .or. (j.eq.(Ny-1)) ) wy = 1.5
         wt = wmxy * wx * wy
         call block9(A,b,mxdim,mxgrd,i,j,Nx,Ny,wt,c,v)
  100 continue
      return
      end
c
c----------------------subroutine Jxy---------------------------------
c      composition of partial block matrix for m2*[(ddf/dxdy)**2]
c      partial derivative at ((xg(i)+xg(i+1))/2,(yg(j)+yg(j+1))/2) :
c              ddf/dxdy = (f(i+,j+1)-f(i+1,j)-f(i,j+1)+f(i,j))/dx*dy
c      double integral is evaluated simply by
c             1    1   - -    1    1       j=Ny
c             1    1   - -    1    1
c             -   -    - -    -    -
c             1    1   - -    1    1       j=2
c             1    1          1    1       j=1
c            i=1  i=2                      i=Nx
c---------------------------------------------------------------------
      subroutine Jxy(a,b,mxdim,mxgrd,Nx,Ny,dx,dy,pm2)
c
      implicit real*8 (a-h,o-z)
      dimension A(mxdim,mxgrd),b(mxdim)
      dimension c(3,3)
c
      call cnull(c)
      c(2,2) =  1.0/(dx*dy)
      c(2,3) = -1.0/(dx*dy)
      c(3,2) = -1.0/(dx*dy)
      c(3,3) =  1.0/(dx*dy)
      wt     = 2.0 * pm2 * dx * dy
      v      = 0.0
      do 100 i=1,Nx-1
      do 100 j=1,Ny-1
         call block9(A,b,mxdim,mxgrd,i,j,Nx,Ny,wt,c,v)
  100 continue
      return
      end
c
c----------------------subroutine block9------------------------------
c      partial block matrix derived from dT/df(i,j) = 0
c      T(f) = (c(1,3)*f(i-1,j+1)+c(2,3)*f(i,j+1)+c(3,3)*f(i+1,j+1)
c             +c(1,2)*f(i-1,j)  +c(2,2)*f(i,j)  +c(3,2)*f(i+1,j)
c             +c(1,1)*f(i-1,j-1)+c(2,1)*f(i,j-1)+c(3.1)*f(i+1,j-1)-v)**2
c             T(f) is given by 3 x 3 elements centering at (i,j) grid
c---------------------------------------------------------------------
      subroutine block9(A,b,mxdim,mxgrd,i,j,Nx,Ny,wt,c,v)
c
      implicit real*8 (a-h,o-z)
      dimension A(mxdim,mxgrd),b(mxdim)
      dimension c(3,3)
c
      do 100 ip=1,3
      do 100 jp=1,3
         k1 = Ny * (i+ip-3) + (j+jp-2)
         if ( (i+ip-3)*(i+ip-Nx-2).gt.0 ) goto 100
         if ( (j+jp-3)*(j+jp-Ny-2).gt.0 ) goto 100
         b(k1) = b(k1) + wt * c(ip,jp) * v
         do 110 iq=1,3
         do 110 jq=1,3
            k2 = Ny * (iq-ip) + (jq-jp+1)
            if (k2.ge.1) A(k1,k2) = A(k1,k2) + wt * c(ip,jp) * c(iq,jq)
  110    continue
  100 continue
      return
      end
c
c----------------------subroutine hmat--------------------------------
c      composition of partial block matrix for elevation residuals
c      residual dev at obsevation point (xh(k),yh(k)) is given by
c        dev = f(xh(k),yh(k)) - zh(k)
c      where xh(k) = xg(i) + cx
c            yh(k) = yg(j) + cy
c  f(xh(k),yh(k))= c(1,3)*f(i-1,j+1)+c(2,3)*f(i,j+1)+c(3,3)*f(i+1,j+1)
c                 +c(1,2)*f(i-1,j)  +c(2,2)*f(i,j)  +c(3,2)*f(i+1,j)
c                 +c(1,1)*f(i-1,j-1)+c(2,1)*f(i,j-1)+c(3.1)*f(i+1,j-1)
c---------------------------------------------------------------------
      subroutine hmat(A,b,mxdim,mxgrd,f,ngrid,Nx,Ny,xmin,ymin,
     &                dx,dy,xh,yh,zh,lm,mxdt,nh,nhdt,alpha)
c
      implicit real*8 (a-h,o-z)
      dimension A(mxdim,mxgrd),b(mxdim)
      dimension f(ngrid,ngrid)
      dimension xh(mxdt),yh(mxdt),zh(mxdt),lm(mxdt)
      dimension c(3,3)
c 
      nhdt = 0
      do 100 k=1,nh
         call gridij(xh(k),yh(k),ih,jh,cx,cy,is,js,
     &               Nx,Ny,xmin,ymin,dx,dy,iflg)
         if (iflg.eq.0) nhdt = nhdt + 1
  100 continue
      if (nhdt .eq. 0) return
c
      wt = alpha/dfloat(nhdt)
      do 200 k=1,nh
         call gridij(xh(k),yh(k),ih,jh,cx,cy,is,js,
     &               Nx,Ny,xmin,ymin,dx,dy,iflg)
         if (iflg .ne. 0) goto 200
         call cfval9(f,ngrid,ih,jh,c,cx,cy,is,js,zc)
         dev = zc - zh(k)
         if ( (lm(k).ne.0) .and. (dev*lm(k).gt.0.0) ) goto 200
         v   = zh(k)
         call block9(A,b,mxdim,mxgrd,ih,jh,Nx,Ny,wt,c,v)
  200 continue
      return
      end
c
c----------------------subroutine cfval9------------------------------
c      coeficients c(1,1),,c(3,3) and elevation at obsevation point
c---------------------------------------------------------------------
      subroutine cfval9(f,ngrid,i,j,c,cx,cy,is,js,zc)
c
      implicit real*8 (a-h,o-z)
      dimension f(ngrid,ngrid)
      dimension c(3,3)
c
      call cnull(c)
c
         c(1,2) = (-cx + cx*cx)/2.0
         c(2,1) = (-cy + cy*cy)/2.0
         c(2,2) = 1.0 - cx*cx - cy*cy
         c(2,3) = (cy + cy*cy)/2.0
         c(3,2) = (cx + cx*cx)/2.0
         c(2+is,2+js) = c(2+is,2+js) + cx*cy
         c(2+is,3+js) = c(2+is,3+js) - cx*cy
         c(3+is,2+js) = c(3+is,2+js) - cx*cy
         c(3+is,3+js) = c(3+is,3+js) + cx*cy
c        value zc = f(xh(k),yh(k))
      zc = 0.0
      do 100 ip=1,3
      do 100 jp=1,3
         zc = zc + c(ip,jp)*f(i+ip-2,j+jp-2)
  100 continue
      return
      end
c
c----------------------subroutine dmat--------------------------------
c     composition of partial block matrix for derivative residuals
c     residual dev at obsevation point (xh(k),yh(k)) is given by
c        fx(xd(k),yd(k)) - dfdx(k)   and  fy(xd(k),yd(k)) - dfdy(k)
c     where both fx(xd(k),yd(k)) and fy(xd(k),yd(k)) are given 
c     in a form : c(1,3)*f(i-1,j+1)+c(2,3)*f(i,j+1)+c(3,3)*f(i+1,j+1)
c                +c(1,2)*f(i-1,j)  +c(2,2)*f(i,j)  +c(3,2)*f(i+1,j)
c                +c(1,1)*f(i-1,j-1)+c(2,1)*f(i,j-1)+c(3.1)*f(i+1,j-1)
c---------------------------------------------------------------------
      subroutine dmat(A,b,mxdim,mxgrd,Nx,Ny,xmin,ymin,dx,dy,
     &                xd,yd,dfdx,dfdy,mxdt,nd,nddt,beta)
c
      implicit real*8 (a-h,o-z)
      dimension A(mxdim,mxgrd),b(mxdim)
      dimension xd(mxdt),yd(mxdt),dfdx(mxdt),dfdy(mxdt)
      dimension c(3,3)
c
      nddt = 0
      do 100 k=1,nd
         call gridij(xd(k),yd(k),id,jd,cx,cy,is,js,Nx,Ny,
     &               xmin,ymin,dx,dy,iflg)
         if (iflg .eq. 0) nddt = nddt + 1
  100 continue
      if (nddt .eq. 0) return
c
      wt = beta/dfloat(nddt)
      do 200 k=1,nd
         call gridij(xd(k),yd(k),id,jd,cx,cy,is,js,Nx,Ny,
     &               xmin,ymin,dx,dy,iflg)
         if (iflg.ne.0) goto 200
c
c           matrix for squred residual of (df/dx)
c
         call cdfdx9(c,cx,cy,is,js,dx)
         v = dfdx(k)
         call block9(A,b,mxdim,mxgrd,id,jd,Nx,Ny,wt,c,v)
c
c           matrix for squared residual of(df/dy)
c
         call cdfdy9(c,cx,cy,is,js,dy)
         v = dfdy(k)
         call block9(A,b,mxdim,mxgrd,id,jd,Nx,Ny,wt,c,v)
  200 continue
      return
      end
c
c----------------------subroutine cdfdx9------------------------------
c      coeficients c(1,1),,c(3,3) for df/dx at an obsevation point
c---------------------------------------------------------------------
      subroutine cdfdx9(c,cx,cy,is,js,dx)
c
      implicit real*8 (a-h,o-z)
      dimension c(3,3)
c
      call cnull(c)
         c(1,2) = (-0.5 + cx)/dx
         c(2,2) = -2.0*cx/dx
         c(3,2) = ( 0.5 + cx)/dx
         c(2+is,2+js) = c(2+is,2+js) + cy/dx
         c(2+is,3+js) = c(2+is,3+js) - cy/dx
         c(3+is,2+js) = c(3+is,2+js) - cy/dx
         c(3+is,3+js) = c(3+is,3+js) + cy/dx
      return
      end
c
c----------------------subroutine cdfdy9------------------------------
c      coeficients c(1,1),,c(3,3) for df/dy at an obsevation point
c---------------------------------------------------------------------
      subroutine cdfdy9(c,cx,cy,is,js,dy)
c
      implicit real*8 (a-h,o-z)
      dimension c(3,3)
c
      call cnull(c)
         c(2,1) = (-0.5 + cy)/dy
         c(2,2) = -2.0*cy/dy
         c(2,3) = ( 0.5 + cy)/dy
         c(2+is,2+js) = c(2+is,2+js) + cx/dy
         c(2+is,3+js) = c(2+is,3+js) - cx/dy
         c(3+is,2+js) = c(3+is,2+js) - cx/dy
         c(3+is,3+js) = c(3+is,3+js) + cx/dy
      return
      end
c
c----------------------subroutine cnull-------------------------------
c                       set c(i,j)=0
c---------------------------------------------------------------------
      subroutine cnull(c)
      implicit real*8 (a-h)
      dimension c(3,3)
      do 100 i=1,3
      do 100 j=1,3
         c(i,j) = 0.0
  100 continue
      return
      end
c
c----------------------subroutine gridij------------------------------
c      find the grid (i,j) nearest to a given point (x,y)
c
c   is=0 js=0        is=-1 js=0       is=-1 js=-1      is=0 js=-1
c       +----+      +----+                 +                +
c       l    l      l    l                 l                l
c       l *  l      l  * l                 l                l
c  +----+----+      +----+----+       +----+----+      +----+----+
c       l                l            l  * l                l *  l
c       l                l            l    l                l    l
c       +                +            +----+                +----+
c---------------------------------------------------------------------
      subroutine gridij(x,y,i,j,cx,cy,is,js,Nx,Ny,xmin,ymin,dx,dy,iflg)
c
      implicit real*8 (a-h,o-z)
c
      iflg = -1
      i = idint( (x - xmin)/dx + 1.50000001 )
         if ((i-1)*(i-Nx) .ge. 0) return
      cx = ( x - (xmin + dfloat(i-1) * dx) )/dx
      is = 0
         if (cx. lt. 0.0) is = -1
c
      j = idint( (y - ymin)/dy + 1.50000001 )
         if ((j-1)*(j-Ny) .ge. 0) return
      cy = ( y - (ymin + dfloat(j-1) * dy) )/dy
      js = 0
         if (cy .lt. 0.0) js = -1
c
      iflg = 0
      return
      end
c
c----------------------subroutine bcholeski---------------------------
c    Choleski's method for simultaneous linear equaltion  A u = b
c    See Togawa(1971,1985) for original program.
c    A : original matrix A is a synmetric band matrix and this subroutine
c        assumes that each element aij is stored at A(i,j-i+1) in memory
c    b : constant terms (input) / solution (output)
c    m : number of unknow
c    nband : half band width (nonzero elements = 2*nband+1)
c    iflg  : flag of calculation   iflg=0   good
c                                  iflg=2   A is singular
c---------------------------------------------------------------------
      subroutine bcholeski(A,b,mxdim,mxgrd,nband,m,iflg)
c
      implicit real*8 (a-h,o-z)
      dimension A(mxdim,mxgrd),b(mxdim)
c
      iflg = 2
      small = 1.0E-10
      nb1   = nband + 1
      mnb   = m - nband
c                              decomposition  A = P'P
      if (A(1,1) .lt. small) return
      A(1,1) = dsqrt(A(1,1))
      do 100 j=2,nb1
         A(1,j) = A(1,j)/A(1,1)
  100 continue
         b(1) = b(1)/A(1,1)
      do 200 i=2,m
         ks = i - nband
            if (i .lt. nb1) ks = 1
         kt = i + nband
            if (i .gt. mnb) kt = m
         im1 = i - 1
         ip1 = i + 1
         sa  = A(i,1)
         sb  = b(i)
         do 120 k=ks,im1
            sa = sa - A(k,ip1-k)**2.0
            sb = sb - A(k,ip1-k)*b(k)
  120    continue
         if (sa .le. small) return
         A(i,1) = dsqrt(sa)
         b(i)   = sb/A(i,1)
            if (i .eq. m) goto 210
            do 180 j=ip1,kt
               sa  = A(i,j-im1)
               jp1 = j + 1
               kks = j - nband
               if (j .lt. nb1) kks = 1
               if (kks .gt. im1) go to 170
               do 160 k=kks,im1
                  sa = sa - A(k,ip1-k)*A(k,jp1-k)
  160          continue
  170          A(i,j-im1) = sa/A(i,1)
  180       continue
  200 continue
c                              solution --> b(i)
  210 b(m) = b(m)/A(m,1)
      do 300 i=m-1,1,-1
         kt  = i + nband
         if (i .gt. mnb) kt = m
         ip1 = i + 1
         im1 = i - 1
         sb=b(i)
         do 220 k=ip1,kt
            sb = sb - A(i,k-im1)*b(k)
  220    continue
         b(i) = sb/A(i,1)
  300 continue
      iflg = 0
      return
      end
c
c----------------------subroutine Jvalue------------------------------
c      Evaluation of J1 and J2 for final solution
c---------------------------------------------------------------------
      subroutine Jvalue(f,ngrid,Nx,Ny,dx,dy,Qj1,Qj2)
c
      implicit real*8 (a-h,o-z)
      dimension f(ngrid,ngrid)
c        Jx
      Qjx = 0.0
      do 100 j=1,Ny
         wy = 1.0
         if ( (j.eq.1) .or. (j.eq.Ny) ) wy = 0.5
      do 100 i=1,Nx-1
         Qjx = Qjx + wy * (f(i+1,j)-f(i,j))**2.0
  100 continue
c        Jy
      Qjy=0.0
      do 110 i=1,Nx
         wx = 1.0
         if ( (i.eq.1) .or. (i.eq.Nx) ) wx = 0.5
      do 110 j=1,Ny-1
        Qjy = Qjy + wx * (f(i,j+1)-f(i,j))**2.0
  110 continue
      Qj1 = (Qjx/dx**2.0 + Qjy/dy**2.0) / (dfloat(Nx-1) * dfloat(Ny-1))
c        Jxx
      Qjxx = 0.0
      do 200 j=1,Ny
         wy = 1.0
         if ( (j.eq.1) .or. (j.eq.Ny) ) wy = 0.5
      do 200 i=2,Nx-1
         wx=1.0
         if ( (i.eq.2) .or. (i.eq.Nx-1) ) wx=1.5
         Qjxx = Qjxx + wx*wy * (f(i+1,j)-2.0*f(i,j)+f(i-1,j))**2.0
  200 continue
c        Jyy
      Qjyy = 0.0
      do 210 i=1,Nx
         wx = 1.0
         if ( (i.eq.1) .or. (i.eq.Nx) ) wx = 0.5
      do 210 j=2,Ny-1
         wy = 1.0
         if ( (j.eq.2) .or. (j.eq.(Ny-1)) ) wy = 1.5
         Qjyy = Qjyy + wx*wy * (f(i,j+1)-2.0*f(i,j)+f(i,j-1))**2.0
  210 continue
c        Jxy
      Qjxy = 0.0
      do 220 i=1,Nx-1
      do 220 j=1,Ny-1
         Qjxy = Qjxy + (f(i+1,j+1)-f(i+1,j)-f(i,j+1)+f(i,j))**2.0
  220 continue
      Qj2 = (Qjxx/dx**4.0+Qjyy/dy**4.0+2.0*Qjxy/(dx*dy)**2.0)*dx*dy
c
c      write(*,30) Qjx,Qjy,Qjxx,Qjyy,2*Qjxy
c   30 format (' Jx =',E12.5,'   Jy =',E12.5/
c     &        ' Jxx=',E12.5,'   Jyy=',E12.5,'  2Jxy=',E12.5)
      return
      end
c
c----------------------subroutine Rhvalue----------------------------
c      Evaluation of Rh (residuals) for final solution
c--------------------------------------------------------------------
      subroutine Rhvalue(f,ngrid,Nx,Ny,dx,dy,xmin,ymin,
     &                   xh,yh,zh,lm,mxdt,nh,nhdt,Qhres)
c
      implicit real*8 (a-h,o-z)
      dimension xh(mxdt),yh(mxdt),zh(mxdt),lm(mxdt)
      dimension f(ngrid,ngrid)
      dimension c(3,3)
c 
      nhdt  = 0
      Qhres = 0.0
      do 100 k=1,nh
         call gridij(xh(k),yh(k),ih,jh,cx,cy,is,js,Nx,Ny,
     &               xmin,ymin,dx,dy,iflg)
         if (iflg.ne.0) goto 100
c
         call cfval9(f,ngrid,ih,jh,c,cx,cy,is,js,zc)
         dev = zc - zh(k)
         if ( (lm(k).ne.0) .and. (dev*lm(k).gt.0.0) ) goto 100
         Qhres = Qhres + dev**2.0
         nhdt  = nhdt + 1
  100 continue
      return
      end
c
c----------------------subroutine Rdvalue----------------------------
c      Evaluation of Rd (residuals) for final solution
c--------------------------------------------------------------------
      subroutine Rdvalue(f,ngrid,Nx,Ny,dx,dy,xmin,ymin,
     &                       xd,yd,dfdx,dfdy,mxdt,nd,nddt,Qdres)
c
      implicit real*8 (a-h,o-z)
      dimension f(ngrid,ngrid)
      dimension xd(mxdt),yd(mxdt)
      dimension dfdx(mxdt),dfdy(mxdt)
      dimension c(3,3)
c
      nddt  = 0
      Qdres = 0.0
      do 100 k=1,nd
         call gridij(xd(k),yd(k),id,jd,cx,cy,is,js,Nx,Ny,
     &               xmin,ymin,dx,dy,iflg)
         if (iflg .ne. 0) goto 100
c     residual for (df/dx)
         call cdfdx9(c,cx,cy,is,js,dx)
         dev = -dfdx(k)
         do 110 i=1,3
         do 110 j=1,3
            dev = dev + c(i,j)*f(id+i-2,jd+j-2)
  110    continue
      Qdres = Qdres + dev**2.0
c     residual for (df/dy)
         call cdfdy9(c,cx,cy,is,js,dy)
         dev = -dfdy(k)
         do 120 i=1,3
         do 120 j=1,3
            dev = dev + c(i,j)*f(id+i-2,jd+j-2)
  120    continue
         Qdres = Qdres + dev**2.0
         nddt = nddt + 1
  100 continue
      return
      end

