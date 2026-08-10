subroutine daxpy(n, a, x, y)
  implicit none
  integer :: n, i
  real(kind=8) :: a
  real(kind=8), dimension(n) :: x, y

  do i = 1, n
    y(i) = a * x(i) + y(i)
  end do
end subroutine daxpy
